"""Lecture des fichiers TLE et construction du catalogue d'objets.

Un fichier TLE de CelesTrak répète ce motif de 3 lignes pour chaque objet :

    ISS (ZARYA)
    1 25544U 98067A   26269.39984369  .00031849  00000+0  59036-3 0  9996
    2 25544  51.6292 159.1757 0007019 184.2024 175.8906 15.48664613587448

La 1re ligne est le nom, les 2 suivantes sont le TLE proprement dit.
"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sgp4.api import Satrec
from sgp4.conveniences import sat_epoch_datetime

EARTH_RADIUS_KM = 6378.135  # rayon équatorial utilisé par SGP4 (modèle WGS-72)
LEO_MAX_ALTITUDE_KM = 2000  # limite conventionnelle de l'orbite basse


@dataclass
class SpaceObject:
    """Un objet en orbite : son identité, son TLE et le modèle SGP4 associé."""

    name: str
    norad_id: str  # numéro de catalogue unique attribué par le NORAD
    group: str  # groupe CelesTrak d'origine
    line1: str
    line2: str
    satrec: Satrec  # le TLE "compris" par SGP4, prêt à calculer des positions

    @property
    def kind(self) -> str:
        """Catégorie de l'objet : débris, Starlink ou autre satellite."""
        if self.group != "active" or "DEB" in self.name:
            return "débris"
        if self.name.startswith("STARLINK"):
            return "Starlink"
        return "satellite"

    @property
    def epoch(self) -> datetime:
        """Date (UTC) à laquelle l'orbite a été mesurée."""
        return sat_epoch_datetime(self.satrec)

    @property
    def perigee_km(self) -> float:
        """Altitude du point le plus bas de l'orbite."""
        return self.satrec.altp * EARTH_RADIUS_KM

    @property
    def apogee_km(self) -> float:
        """Altitude du point le plus haut de l'orbite."""
        return self.satrec.alta * EARTH_RADIUS_KM


def read_tle_file(path: Path, group: str) -> list[SpaceObject]:
    """Lit un fichier TLE et renvoie un SpaceObject par objet."""
    lines = [line.rstrip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    objects = []
    for i in range(0, len(lines) - 2, 3):
        name, line1, line2 = lines[i], lines[i + 1], lines[i + 2]
        satrec = Satrec.twoline2rv(line1, line2)
        objects.append(SpaceObject(name.strip(), line1[2:7].strip(), group, line1, line2, satrec))
    return objects


def load_catalog(files: dict[str, Path]) -> list[SpaceObject]:
    """Assemble tous les groupes en un seul catalogue, sans doublons."""
    catalog: dict[str, SpaceObject] = {}
    for group, path in files.items():
        for obj in read_tle_file(path, group):
            catalog.setdefault(obj.norad_id, obj)  # garde la 1re occurrence
    return list(catalog.values())


def filter_leo(objects: list[SpaceObject]) -> list[SpaceObject]:
    """Garde uniquement les objets dont toute l'orbite est sous 2 000 km."""
    return [obj for obj in objects if obj.apogee_km < LEO_MAX_ALTITUDE_KM]


def decode_tle(line1: str, line2: str) -> list[tuple[str, str, str]]:
    """Découpe un TLE en champs : (nom du champ, texte brut, signification).

    Le format TLE est à colonnes fixes : chaque information occupe toujours
    les mêmes positions dans la ligne (héritage des cartes perforées).
    """
    epoch_year = int(line1[18:20])
    epoch_year += 2000 if epoch_year < 57 else 1900  # années sur 2 chiffres
    eccentricity = "0." + line2[26:33]  # le "0." est sous-entendu dans le TLE

    return [
        ("Numéro NORAD", line1[2:7], "Identifiant unique de l'objet"),
        ("Désignation internationale", line1[9:17], "Année + numéro du lancement + pièce"),
        ("Époque", line1[18:32], f"Date de mesure : jour {float(line1[20:32]):.4f} de {epoch_year}"),
        ("BSTAR", line1[53:61], "Sensibilité au freinage atmosphérique"),
        ("Inclinaison", line2[8:16], "Angle entre l'orbite et l'équateur (degrés)"),
        ("Ascension droite du nœud", line2[17:25], "Orientation du plan de l'orbite (degrés)"),
        ("Excentricité", line2[26:33], f"{eccentricity} : 0 = cercle parfait, proche de 1 = très allongée"),
        ("Argument du périgée", line2[34:42], "Position du point le plus bas dans l'orbite (degrés)"),
        ("Anomalie moyenne", line2[43:51], "Position de l'objet sur son orbite à l'époque (degrés)"),
        ("Mouvement moyen", line2[52:63], "Nombre de tours de la Terre par jour"),
    ]
