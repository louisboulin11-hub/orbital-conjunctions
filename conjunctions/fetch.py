"""Téléchargement des TLE depuis CelesTrak, avec un cache local.

CelesTrak demande de ne pas re-télécharger les mêmes données plus d'une fois
toutes les 2 heures (elles ne sont de toute façon pas mises à jour plus souvent).
On garde donc une copie de chaque fichier dans data/ et on la réutilise tant
qu'elle a moins de 2 heures.
"""

import time
from pathlib import Path

import requests

CELESTRAK_URL = "https://celestrak.org/NORAD/elements/gp.php"

# Groupes CelesTrak téléchargés : nom du groupe -> description lisible
GROUPS = {
    "active": "Satellites actifs",
    "cosmos-2251-debris": "Débris Cosmos 2251 (collision de 2009)",
    "iridium-33-debris": "Débris Iridium 33 (collision de 2009)",
    "fengyun-1c-debris": "Débris Fengyun 1C (tir antisatellite de 2007)",
}

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
MAX_CACHE_AGE_S = 2 * 3600  # 2 heures, en secondes


def fetch_group(group: str, force: bool = False) -> Path:
    """Renvoie le chemin du fichier TLE d'un groupe, en le téléchargeant si besoin."""
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / f"{group}.tle"

    # Si une copie récente existe, on la réutilise sans rien télécharger
    if path.exists() and not force:
        age_s = time.time() - path.stat().st_mtime
        if age_s < MAX_CACHE_AGE_S:
            return path

    response = requests.get(
        CELESTRAK_URL,
        params={"GROUP": group, "FORMAT": "tle"},
        timeout=30,
    )

    # 403 = CelesTrak refuse car on a déjà téléchargé ces données et elles
    # n'ont pas changé depuis. Si on a une copie (même ancienne), on s'en sert.
    if response.status_code == 403:
        if path.exists():
            return path
        raise RuntimeError(
            f"CelesTrak refuse le téléchargement de '{group}' et aucune copie locale "
            f"n'existe. Message du serveur :\n{response.text.strip()}"
        )

    response.raise_for_status()  # lève une erreur si le serveur répond 404, 500...

    # CelesTrak peut répondre "200 OK" avec un message d'erreur en texte :
    # on vérifie qu'on a bien reçu des TLE avant d'écraser le cache.
    text = response.text
    if "\n1 " not in text or "\n2 " not in text:
        raise RuntimeError(f"Réponse inattendue de CelesTrak pour '{group}' : {text[:200]!r}")

    path.write_text(text, encoding="utf-8")
    return path


def fetch_all(force: bool = False) -> dict[str, Path]:
    """Télécharge (ou lit en cache) tous les groupes de GROUPS."""
    return {group: fetch_group(group, force) for group in GROUPS}


# Contours des côtes (base cartographique libre Natural Earth, échelle 1:110 000 000)
COASTLINES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_110m_coastline.geojson"
)


def fetch_coastlines() -> Path:
    """Renvoie le fichier GeoJSON des côtes, téléchargé une seule fois (les côtes ne bougent pas)."""
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / "coastlines.geojson"
    if not path.exists():
        response = requests.get(COASTLINES_URL, timeout=30)
        response.raise_for_status()
        path.write_text(response.text, encoding="utf-8")
    return path


# Catalogue des objets (SATCAT) : type, statut opérationnel, pays propriétaire...
# Un seul fichier pour tous les objets, mis à jour une fois par jour par CelesTrak.
SATCAT_URL = "https://celestrak.org/pub/satcat.csv"
SATCAT_MAX_AGE_S = 24 * 3600  # 24 heures : inutile de le télécharger plus souvent


def fetch_satcat(force: bool = False) -> Path:
    """Renvoie le fichier SATCAT (CSV), re-téléchargé au plus une fois par jour."""
    DATA_DIR.mkdir(exist_ok=True)
    path = DATA_DIR / "satcat.csv"
    if path.exists() and not force and time.time() - path.stat().st_mtime < SATCAT_MAX_AGE_S:
        return path

    response = requests.get(SATCAT_URL, timeout=60)
    if response.status_code == 403 and path.exists():  # refus de CelesTrak : on garde la copie
        return path
    response.raise_for_status()
    if not response.text.startswith("OBJECT_NAME,"):  # on vérifie l'en-tête avant d'écraser le cache
        raise RuntimeError(f"Réponse inattendue de CelesTrak (SATCAT) : {response.text[:200]!r}")
    path.write_text(response.text, encoding="utf-8")
    return path
