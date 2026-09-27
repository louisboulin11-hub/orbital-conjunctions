"""Détection des paires d'objets qui passent près l'une de l'autre.

On procède en entonnoir pour éviter de comparer les ~160 millions de paires
à chaque instant :

1. Filtre par altitude : deux objets dont les tranches d'altitude (périgée ->
   apogée) ne se chevauchent pas ne peuvent jamais se croiser.
2. Filtre grossier : à chaque instant d'une grille de temps, un KD-tree trouve
   les paires plus proches qu'un seuil élargi (voir coarse_threshold_km), puis
   une estimation "en ligne droite" élimine celles qui ne s'approchent pas assez.
3. Raffinement (étape suivante) : calcul précis de l'instant et de la distance
   du rapprochement maximal pour les seules paires retenues.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from sgp4.api import SatrecArray

from .catalog import SpaceObject
from .propagate import iter_time_chunks

# Vitesse relative maximale entre deux objets en orbite basse : deux objets à
# ~7,9 km/s qui se croisent de face. On arrondit au-dessus par sécurité.
MAX_RELATIVE_SPEED_KM_S = 16.0

# Marge ajoutée au seuil lors de l'estimation "en ligne droite" : sur quelques
# secondes, la courbure réelle des trajectoires ne l'écarte que de quelques mètres.
LINEAR_MARGIN_KM = 1.0


def coarse_threshold_km(threshold_km: float, step_s: float) -> float:
    """Seuil élargi à utiliser sur la grille de temps pour ne rater aucun rapprochement.

    Le rapprochement maximal a lieu au plus à step_s / 2 d'un instant de la grille.
    Pendant ce temps, les deux objets s'écartent d'au plus MAX_RELATIVE_SPEED * step_s / 2.
    """
    return threshold_km + MAX_RELATIVE_SPEED_KM_S * step_s / 2


def count_altitude_overlaps(objects: list[SpaceObject], margin_km: float) -> int:
    """Nombre de paires dont les tranches d'altitude se chevauchent (à margin_km près).

    Astuce : on trie les objets par périgée. Pour un objet i, ses partenaires
    possibles situés après lui dans le tri sont ceux dont le périgée est sous
    son apogée (+ marge). Une recherche dichotomique (searchsorted) les compte
    sans avoir à énumérer les paires une par une.
    """
    perigees = np.array([obj.perigee_km for obj in objects])
    apogees = np.array([obj.apogee_km for obj in objects])
    order = np.argsort(perigees)
    perigees, apogees = perigees[order], apogees[order]

    last_partner = np.searchsorted(perigees, apogees + margin_km, side="right")
    return int(np.sum(last_partner - np.arange(1, len(objects) + 1)))


def linear_closest_approach(
    dr: np.ndarray, dv: np.ndarray, half_window_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Rapprochement maximal en supposant un mouvement relatif en ligne droite.

    dr, dv : positions et vitesses relatives (une ligne par paire).
    La distance au temps tau vaut |dr + dv * tau| ; elle est minimale pour
    tau = -(dr . dv) / |dv|^2. On limite tau à la fenêtre [-half_window_s, +half_window_s]
    autour de l'instant de grille, où l'approximation "ligne droite" est valable.
    Renvoie (tau en secondes, distance minimale en km).
    """
    dv2 = np.sum(dv * dv, axis=1)
    safe_dv2 = np.where(dv2 > 0, dv2, 1.0)  # évite une division par zéro
    tau = np.where(dv2 > 0, -np.sum(dr * dv, axis=1) / safe_dv2, 0.0)
    tau = np.clip(tau, -half_window_s, half_window_s)
    distance = np.linalg.norm(dr + dv * tau[:, None], axis=1)
    return tau, distance


@dataclass
class ScreeningResult:
    """Résultat du filtre grossier, avec les compteurs de chaque étage de l'entonnoir."""

    hits: pd.DataFrame  # une ligne par (paire, instant) retenue après le filtre linéaire
    kdtree_pairs: int  # paires distinctes trouvées par le KD-tree (avant filtre linéaire)
    kdtree_hits: int  # couples (paire, instant) trouvés par le KD-tree


def coarse_screen(
    objects: list[SpaceObject],
    start: datetime,
    duration_s: float,
    step_s: float,
    threshold_km: float,
    chunk_s: float = 1800,
) -> ScreeningResult:
    """Filtre grossier : paires susceptibles de passer à moins de threshold_km.

    À chaque instant de la grille :
      a) le KD-tree trouve les paires à moins de coarse_threshold_km(threshold_km, step_s) ;
      b) pour ces paires, on estime le rapprochement maximal en ligne droite
         et on ne garde que celles sous threshold_km + LINEAR_MARGIN_KM.
    """
    satrecs = SatrecArray([obj.satrec for obj in objects])
    search_radius_km = coarse_threshold_km(threshold_km, step_s)
    n = len(objects)
    hits = []
    kdtree_codes = np.array([], dtype=np.int64)  # identifiants des paires vues par le KD-tree
    kdtree_hits = 0

    for times_s, r, v, errors in iter_time_chunks(satrecs, start, duration_s, step_s, chunk_s):
        chunk_codes = []
        for k, t in enumerate(times_s):
            # On écarte les objets pour lesquels SGP4 a échoué à cet instant
            valid = np.flatnonzero(errors[:, k] == 0)
            positions = r[valid, k, :]

            # a) Le KD-tree range les positions dans des "boîtes" imbriquées, ce qui
            #    permet de trouver les voisins proches sans tester toutes les paires.
            pairs = cKDTree(positions).query_pairs(search_radius_km, output_type="ndarray")
            if len(pairs) == 0:
                continue
            i = valid[np.minimum(pairs[:, 0], pairs[:, 1])]  # retour aux indices du catalogue
            j = valid[np.maximum(pairs[:, 0], pairs[:, 1])]
            kdtree_hits += len(pairs)
            chunk_codes.append(i.astype(np.int64) * n + j)  # un nombre unique par paire

            # b) Estimation en ligne droite du rapprochement autour de cet instant
            tau, distance = linear_closest_approach(r[j, k] - r[i, k], v[j, k] - v[i, k], step_s / 2)
            keep = distance < threshold_km + LINEAR_MARGIN_KM
            if keep.any():
                hits.append(
                    pd.DataFrame(
                        {"i": i[keep], "j": j[keep], "t_s": t,
                         "tca_s": t + tau[keep], "distance_km": distance[keep]}
                    )
                )
        if chunk_codes:
            kdtree_codes = np.union1d(kdtree_codes, np.concatenate(chunk_codes))

    columns = ["i", "j", "t_s", "tca_s", "distance_km"]
    table = pd.concat(hits, ignore_index=True) if hits else pd.DataFrame(columns=columns)
    return ScreeningResult(table, len(kdtree_codes), kdtree_hits)
