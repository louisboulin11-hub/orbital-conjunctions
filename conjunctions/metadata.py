"""Métadonnées des objets : type, statut opérationnel, pays et famille (constellation).

Source : le SATCAT de CelesTrak (catalogue de tous les objets suivis). Attention :
son champ OWNER est surtout un code PAYS (US, PRC, UK...), pas une entreprise :
Starlink (SpaceX) et Kuiper (Amazon) y sont tous deux "US". Pour distinguer les
opérateurs, on reconnaît donc les grandes familles de satellites au préfixe de leur nom.
"""

import re

import pandas as pd

from .catalog import SpaceObject
from .fetch import fetch_satcat

# Statuts considérés comme "actifs" par CelesTrak : opérationnel (+), partiellement (P),
# réserve (B), en attente d'activation (S), mission prolongée (X)
ACTIVE_STATUS = {"+", "P", "B", "S", "X"}

# Familles reconnues au préfixe du nom : préfixe -> nom affiché.
# Liste écrite à la main à partir des familles les plus nombreuses du catalogue. Quand
# l'opérateur exact n'est pas certain, on nomme la famille plutôt qu'une entreprise.
# Volontairement absents : les préfixes "2023", "2024"... (objets sans nom) et
# "TRANSPORTER" (vols groupés réunissant des satellites de clients différents).
FAMILIES = {
    "STARLINK": "Starlink (SpaceX)",
    "ONEWEB": "OneWeb",
    "KUIPER": "Kuiper (Amazon)",
    "QIANFAN": "Qianfan",
    "HULIANWANG": "Hulianwang",
    "GUOWANG": "Guowang",
    "YAOGAN": "Yaogan",
    "COSMOS": "Cosmos (Russie)",
    "FLOCK": "Flock (Planet)",
    "LEMUR": "Lemur (Spire)",
    "IRIDIUM": "Iridium",
    "GLOBALSTAR": "Globalstar",
    "ORBCOMM": "ORBCOMM",
    "ICEYE": "ICEYE",
    "JILIN": "Jilin",
    "GAOFEN": "Gaofen",
    "TIANQI": "Tianqi",
    "CENTISPACE": "Centispace",
    "GEESAT": "Geesat",
    "IRIDE": "IRIDE",
    "HAWK": "Hawk (HawkEye 360)",
}


def norad_key(norad_id: str) -> str:
    """Numéro NORAD sans zéros de tête : le TLE écrit "00900", le SATCAT écrit "900"."""
    return norad_id.strip().lstrip("0") or "0"


def name_prefix(name: str) -> str:
    """Premier mot du nom, avant un espace, un tiret ou une parenthèse : "STARLINK-1234" -> "STARLINK"."""
    return re.split(r"[\s\-(]", name.strip(), maxsplit=1)[0].upper()


def load_satcat() -> pd.DataFrame:
    """Le SATCAT, indexé par numéro NORAD (sans zéros de tête)."""
    satcat = pd.read_csv(fetch_satcat(), dtype=str, keep_default_na=False)
    satcat["key"] = satcat["NORAD_CAT_ID"].map(norad_key)
    return satcat.set_index("key")


def build_metadata(objects: list[SpaceObject]) -> pd.DataFrame:
    """Une ligne par objet du catalogue, indexée par numéro NORAD tel qu'écrit dans nos TLE.

    Colonnes :
      in_satcat   l'objet a-t-il été trouvé dans le SATCAT ?
      object_type PAY (satellite), R/B (corps de fusée), DEB (débris), UNK (inconnu)
      ops_status  code de statut opérationnel du SATCAT
      owner       code pays / organisation du SATCAT (US, PRC, UK...)
      active      statut opérationnel "actif" au sens de CelesTrak
      family      famille reconnue au préfixe du nom (vide si non reconnue)
      operator    famille si reconnue, sinon "non identifié (pays)" pour un actif, vide sinon
    """
    satcat = load_satcat()
    rows = []
    for obj in objects:
        key = norad_key(obj.norad_id)
        found = key in satcat.index
        record = satcat.loc[key] if found else None
        status = record["OPS_STATUS_CODE"] if found else ""
        owner = record["OWNER"] if found else ""
        active = status in ACTIVE_STATUS
        family = FAMILIES.get(name_prefix(obj.name), "") if active else ""
        rows.append({
            "norad_id": obj.norad_id,
            "name": obj.name,
            "in_satcat": found,
            "object_type": record["OBJECT_TYPE"] if found else "",
            "ops_status": status,
            "owner": owner,
            "active": active,
            "family": family,
            "operator": family or (f"non identifié ({owner or '?'})" if active else ""),
        })
    return pd.DataFrame(rows).set_index("norad_id")
