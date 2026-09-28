"""Répartition des objets et des rapprochements par tranche d'altitude.

Les satellites actifs ont des orbites quasi circulaires (altitude presque constante),
mais les débris sont souvent elliptiques et traversent plusieurs tranches à chaque tour.
On ne range donc pas un objet dans UNE tranche : on mesure la fraction de son temps
passée dans chacune ("temps de présence").
"""

import math
from datetime import datetime

import numpy as np
import pandas as pd
from sgp4.api import SatrecArray

from .catalog import EARTH_RADIUS_KM, SpaceObject
from .propagate import iter_time_chunks, julian_date

BAND_WIDTH_KM = 100
PRESENCE_WINDOW_S = 2.5 * 3600  # couvre au moins un tour complet pour tout objet en orbite basse
PRESENCE_STEP_S = 30.0


def band_of(altitude_km: np.ndarray, width_km: float = BAND_WIDTH_KM) -> np.ndarray:
    """Borne basse de la tranche d'altitude : 437 km -> 400 (tranche 400-500 km)."""
    return (np.floor(np.asarray(altitude_km) / width_km) * width_km).astype(int)


def presence_by_band(objects: list[SpaceObject], start: datetime,
                     width_km: float = BAND_WIDTH_KM) -> pd.DataFrame:
    """Fraction du temps passée par chaque objet dans chaque tranche d'altitude.

    Renvoie un tableau (une ligne par objet, indexée par numéro NORAD ; une colonne par
    borne basse de tranche) dont chaque ligne somme à 1. Exemple : un débris qui passe
    60 % de son orbite entre 700 et 800 km a 0,6 dans la colonne 700.
    """
    longest_period_s = max(2 * math.pi / obj.satrec.no_kozai * 60 for obj in objects)
    if longest_period_s > PRESENCE_WINDOW_S:
        raise ValueError(f"Fenêtre trop courte pour couvrir un tour complet ({longest_period_s:.0f} s)")

    bands = np.arange(0, 2000, width_km).astype(int)
    counts = np.zeros((len(objects), len(bands)))
    satrecs = SatrecArray([obj.satrec for obj in objects])
    for _, r, _, errors in iter_time_chunks(satrecs, start, PRESENCE_WINDOW_S, PRESENCE_STEP_S, 1800):
        altitude = np.linalg.norm(r, axis=2) - EARTH_RADIUS_KM  # (objets, instants)
        index = np.clip(band_of(np.nan_to_num(altitude), width_km) // width_km, 0, len(bands) - 1)
        valid = errors == 0  # on ignore les instants où SGP4 a échoué
        for k in range(len(bands)):
            counts[:, k] += ((index == k) & valid).sum(axis=1)

    totals = counts.sum(axis=1, keepdims=True)
    fractions = np.divide(counts, totals, out=np.zeros_like(counts), where=totals > 0)
    return pd.DataFrame(fractions, index=[obj.norad_id for obj in objects], columns=bands)


def shell_volume_km3(low_km: float, width_km: float = BAND_WIDTH_KM) -> float:
    """Volume de la coquille sphérique entre les altitudes low_km et low_km + width_km.

    Différence entre deux boules : (4/3)·π·(r2³ - r1³). À épaisseur égale, une tranche
    haute est plus volumineuse qu'une tranche basse, car elle est plus loin du centre.
    """
    r1 = EARTH_RADIUS_KM + low_km
    r2 = r1 + width_km
    return 4 / 3 * math.pi * (r2 ** 3 - r1 ** 3)


def density_table(presence: pd.DataFrame, active: pd.Series, event_bands: pd.Series,
                  hours: float, width_km: float = BAND_WIDTH_KM) -> pd.DataFrame:
    """Densité d'objets et de rapprochements par tranche d'altitude.

    presence : temps de présence de chaque objet par tranche (presence_by_band)
    active : True pour les objets actifs, indexé comme `presence`
    event_bands : tranche d'altitude de chaque rapprochement (au TCA)
    hours : durée de la détection, pour ramener les rapprochements à une journée

    "Rapprochements par objet et par jour" = 2 × rapprochements ÷ objets, car chaque
    rapprochement implique deux objets. Si les objets se croisaient comme les molécules
    d'un gaz, cette valeur serait proportionnelle à la densité : le rapport des deux
    serait alors à peu près le même d'une tranche à l'autre.
    """
    is_active = active.reindex(presence.index).fillna(False).astype(bool).to_numpy()
    events_per_band = event_bands.dropna().astype(int).value_counts()
    rows = []
    for band in presence.columns:
        objects = presence[band].sum()
        events = int(events_per_band.get(band, 0))
        if objects < 0.5 and events == 0:
            continue  # tranche vide
        volume = shell_volume_km3(band, width_km)
        density = objects / volume * 1e9  # objets par milliard de km³
        per_day = events * 24 / hours
        pressure = 2 * per_day / objects if objects > 0 else float("nan")
        rows.append({
            "band": int(band),
            "objects": objects,
            "active_objects": presence[band][is_active].sum(),
            "inactive_objects": presence[band][~is_active].sum(),
            "density": density,
            "events_per_day": per_day,
            "events_per_object_per_day": pressure,
            "pressure_over_density": pressure / density if density > 0 else float("nan"),
        })
    return pd.DataFrame(rows)


def event_altitudes(events: pd.DataFrame, objects: list[SpaceObject]) -> np.ndarray:
    """Altitude (km) de chaque rapprochement au TCA, calculée avec SGP4 sur le premier objet.

    Les deux objets sont à moins de 5 km l'un de l'autre : prendre l'un ou l'autre ne change
    pas la tranche. NaN si l'objet n'est plus dans le catalogue.
    """
    by_norad = {obj.norad_id: obj for obj in objects}
    altitudes = np.full(len(events), np.nan)
    for k, (norad_id, tca) in enumerate(zip(events["norad_1"], events["tca_utc"])):
        obj = by_norad.get(norad_id)
        if obj is None:
            continue
        error, r, _ = obj.satrec.sgp4(*julian_date(tca))
        if error == 0:
            altitudes[k] = math.hypot(*r) - EARTH_RADIUS_KM
    return altitudes
