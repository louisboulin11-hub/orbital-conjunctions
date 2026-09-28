"""Classement des rapprochements selon les acteurs en présence (congestion, exposition, pollution).

Rappel : une distance nominale sous le seuil n'est PAS une mesure de risque (TLE précis
à ~1 km, manœuvres autonomes de certaines constellations). Ce classement décrit QUI se
croise de près, pas qui court un danger.
"""

import pandas as pd

# Catégories, dans l'ordre d'affichage : (code, libellé)
CATEGORIES = [
    ("intra", "Intra-constellation (congestion interne)"),
    ("inter", "Inter-opérateurs (exposition)"),
    ("undetermined", "Actifs, opérateur indéterminé"),
    ("active_inactive", "Actif / objet inactif (pollution)"),
    ("inactive_inactive", "Inactif / inactif (pollution)"),
    ("unclassified", "Non classé (absent du SATCAT)"),
]
LABELS = dict(CATEGORIES)


def classify_pair(a: pd.Series, b: pd.Series) -> str:
    """Catégorie d'un rapprochement entre deux objets décrits par build_metadata."""
    if not (a["in_satcat"] and b["in_satcat"]):
        return "unclassified"
    if a["active"] and b["active"]:
        if a["family"] and b["family"]:  # deux familles reconnues
            return "intra" if a["family"] == b["family"] else "inter"
        if a["family"] or b["family"]:  # une seule reconnue : on suppose deux opérateurs différents
            return "inter"
        # Aucune reconnue : des pays différents impliquent des opérateurs différents,
        # un même pays ne permet pas de conclure
        return "inter" if a["owner"] != b["owner"] else "undetermined"
    if a["active"] or b["active"]:
        return "active_inactive"
    return "inactive_inactive"


def classify_events(events: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    """Ajoute aux rapprochements la catégorie et l'opérateur (ou famille) de chaque objet."""
    classified = events.copy()
    # reindex : un objet absent des métadonnées (retombé depuis la détection, par exemple)
    # donne une ligne vide, que l'on remplit pour qu'il ne passe jamais pour un objet actif
    # (attention : en Python, une valeur manquante NaN est considérée comme "vraie").
    empty = {"in_satcat": False, "active": False, "family": "", "owner": "", "operator": ""}
    meta_1 = metadata.reindex(events["norad_1"]).fillna(empty).reset_index(drop=True)
    meta_2 = metadata.reindex(events["norad_2"]).fillna(empty).reset_index(drop=True)
    classified["category"] = [classify_pair(a, b) for (_, a), (_, b) in
                              zip(meta_1.iterrows(), meta_2.iterrows())]
    classified["operator_1"] = meta_1["operator"].to_numpy()
    classified["operator_2"] = meta_2["operator"].to_numpy()
    return classified


def summarize_categories(classified: pd.DataFrame) -> pd.DataFrame:
    """Tableau récapitulatif : nombre et part des rapprochements par catégorie."""
    total = len(classified)
    rows = []
    for code, label in CATEGORIES:
        group = classified[classified["category"] == code]
        rows.append({
            "catégorie": label,
            "rapprochements": len(group),
            "part (%)": 100 * len(group) / total if total else 0.0,
            "dont < 1 km": int((group["miss_distance_km"] < 1).sum()),
            "vitesse rel. médiane (km/s)": group["relative_speed_km_s"].median() if len(group) else None,
        })
    return pd.DataFrame(rows)
