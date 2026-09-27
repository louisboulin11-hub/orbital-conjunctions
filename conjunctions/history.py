"""TLE historiques, téléchargés depuis Space-Track.org (compte gratuit requis).

Space-Track est le site officiel qui publie les TLE produits par l'armée américaine.
Son service "gp_history" archive tous les TLE publiés depuis le début de l'ère spatiale.

Les identifiants ne sont jamais écrits dans le code : ils sont demandés au clavier lors du
premier téléchargement (ou lus dans les variables SPACETRACK_USER et SPACETRACK_PASSWORD).
Les conditions d'utilisation interdisent de redistribuer les données : les fichiers
téléchargés restent dans data/history/, exclu de Git.
"""

import getpass
import os
from datetime import datetime
from functools import cache
from pathlib import Path

import requests

from .catalog import SpaceObject, read_tle_file
from .fetch import DATA_DIR

SPACETRACK_URL = "https://www.space-track.org"
HISTORY_DIR = DATA_DIR / "history"


@cache
def ask_credentials() -> tuple[str, str]:
    """Identifiants Space-Track : variables d'environnement si elles existent, sinon saisie au clavier.

    getpass masque la saisie du mot de passe, qui n'est ainsi ni affiché, ni enregistré
    dans l'historique du terminal, ni écrit dans un fichier. @cache : on ne les demande
    qu'une fois par exécution, même si plusieurs historiques sont téléchargés.
    """
    user = os.environ.get("SPACETRACK_USER")
    password = os.environ.get("SPACETRACK_PASSWORD")
    if user and password:
        return user, password
    try:
        user = user or input("Identifiant Space-Track (e-mail) : ")
        password = getpass.getpass("Mot de passe Space-Track (la saisie reste invisible) : ")
    except EOFError:  # personne ne peut taper (programme lancé en arrière-plan)
        raise RuntimeError("Identifiants Space-Track manquants : lancez python backtest.py "
                           "dans un terminal pour les saisir.") from None
    return user, password


def fetch_history(norad_ids: list[str], first_day: datetime, last_day: datetime) -> Path:
    """Tous les TLE des objets `norad_ids` dont l'époque tombe entre first_day et last_day inclus.

    Le fichier est mis en cache : un historique ne change plus, on ne le télécharge qu'une fois.
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ids = ",".join(sorted(norad_ids))
    path = HISTORY_DIR / f"{ids.replace(',', '_')}_{first_day:%Y%m%d}_{last_day:%Y%m%d}.tle"
    if path.exists():
        return path

    user, password = ask_credentials()

    # Requête : classe gp_history, objets choisis, intervalle d'époques, tri chronologique,
    # format "3le" (une ligne de nom "0 NOM" puis les deux lignes du TLE)
    query = (f"/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{ids}"
             f"/EPOCH/{first_day:%Y-%m-%d}--{last_day:%Y-%m-%d}/orderby/EPOCH%20asc/format/3le")

    # Une "session" garde le cookie de connexion entre la connexion et la requête
    with requests.Session() as session:
        login = session.post(f"{SPACETRACK_URL}/ajaxauth/login",
                             data={"identity": user, "password": password}, timeout=30)
        login.raise_for_status()
        if "Failed" in login.text:  # Space-Track répond "200 OK" même si le mot de passe est faux
            raise RuntimeError("Space-Track a refusé les identifiants.")
        response = session.get(SPACETRACK_URL + query, timeout=120)
        response.raise_for_status()
        session.get(f"{SPACETRACK_URL}/ajaxauth/logout", timeout=30)

    if "\n1 " not in response.text and not response.text.startswith("1 "):
        raise RuntimeError(f"Aucun TLE reçu de Space-Track : {response.text[:200]!r}")
    path.write_text(response.text, encoding="utf-8")
    return path


def read_history(path: Path) -> list[SpaceObject]:
    """Lit un fichier d'historique : plusieurs TLE successifs par objet, dans l'ordre chronologique."""
    elsets = read_tle_file(path, group="history")
    for elset in elsets:
        elset.name = elset.name.removeprefix("0 ")  # format 3le : le nom est précédé de "0 "
    return sorted(elsets, key=lambda elset: elset.epoch)
