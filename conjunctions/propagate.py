"""Calcul des positions avec SGP4, et conversion en latitude / longitude / altitude.

SGP4 donne la position dans le repère TEME : centré sur la Terre, mais dont les
axes restent fixes par rapport aux étoiles (il ne tourne pas avec la Terre).
Pour savoir au-dessus de quel point du globe se trouve un objet, il faut donc
tenir compte de la rotation de la Terre à l'instant considéré.
"""

import math
from datetime import datetime, timezone

import numpy as np
from sgp4.api import Satrec, jday
from sgp4.propagation import gstime

# Ellipsoïde WGS-84 : la forme de la Terre (légèrement aplatie aux pôles) utilisée par le GPS
WGS84_A_KM = 6378.137  # rayon à l'équateur
WGS84_F = 1 / 298.257223563  # aplatissement : le rayon polaire est ~21 km plus court
WGS84_E2 = WGS84_F * (2 - WGS84_F)  # excentricité de l'ellipsoïde, au carré


def julian_date(t: datetime) -> tuple[float, float]:
    """Convertit une date en "jour julien", le format de date attendu par SGP4.

    Le jour julien compte les jours écoulés depuis l'an -4712 : c'est un simple
    nombre, pratique pour les calculs astronomiques. SGP4 le veut en deux morceaux
    (partie entière + fraction du jour) pour garder une précision à la milliseconde.
    """
    t = t.astimezone(timezone.utc)
    return jday(t.year, t.month, t.day, t.hour, t.minute, t.second + t.microsecond / 1e6)


def propagate(satrec: Satrec, t: datetime) -> tuple[np.ndarray, np.ndarray]:
    """Position (km) et vitesse (km/s) d'un objet à l'instant t, dans le repère TEME."""
    jd, fr = julian_date(t)
    error, r, v = satrec.sgp4(jd, fr)
    if error != 0:
        # Ex. : objet déjà retombé dans l'atmosphère à la date demandée
        raise ValueError(f"SGP4 a échoué (code {error}) pour l'objet {satrec.satnum}")
    return np.array(r), np.array(v)


def teme_to_geodetic(r: np.ndarray, t: datetime) -> tuple[float, float, float]:
    """Convertit une position TEME en (latitude °, longitude °, altitude km)."""
    # 1. Angle dont la Terre a tourné à l'instant t (temps sidéral moyen de Greenwich)
    jd, fr = julian_date(t)
    theta = gstime(jd + fr)

    # 2. On "tourne" la position de -theta autour de l'axe des pôles pour passer
    #    dans un repère attaché à la Terre (l'axe x traverse le méridien de Greenwich)
    x, y, z = r
    x_earth = x * math.cos(theta) + y * math.sin(theta)
    y_earth = -x * math.sin(theta) + y * math.cos(theta)

    # 3. Longitude : l'angle dans le plan de l'équateur, compté depuis Greenwich
    lon = math.atan2(y_earth, x_earth)

    # 4. Latitude et altitude : la Terre étant aplatie, il n'y a pas de formule
    #    directe. On part d'une approximation et on l'affine quelques fois
    #    (chaque tour gagne plusieurs décimales : 5 tours suffisent largement).
    p = math.hypot(x_earth, y_earth)  # distance à l'axe des pôles
    lat = math.atan2(z, p * (1 - WGS84_E2))
    for _ in range(5):
        n = WGS84_A_KM / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
        alt = p / math.cos(lat) - n
        lat = math.atan2(z, p * (1 - WGS84_E2 * n / (n + alt)))
    n = WGS84_A_KM / math.sqrt(1 - WGS84_E2 * math.sin(lat) ** 2)
    alt = p / math.cos(lat) - n

    return math.degrees(lat), math.degrees(lon), alt
