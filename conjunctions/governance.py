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


MIN_EXPECTED_EVENTS = 10  # en dessous, l'indice n'est pas affiché (trop peu d'événements)


def expected_shares(metadata: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Part attendue de chaque catégorie si chaque paire d'objets avait la même chance de se croiser.

    weights : poids de chaque objet (1 pour le calcul global ; son temps de présence dans une
    tranche pour le calcul par altitude). Le poids d'une paire est le produit des poids des
    deux objets. On applique à ces paires la MÊME fonction classify_pair qu'aux
    rapprochements observés, pour que les deux côtés utilisent les mêmes définitions.

    Astuce de calcul : on regroupe les objets de profil identique (mêmes champs utilisés
    par classify_pair). Avec P = somme des poids d'un groupe et Q = somme des carrés, le poids
    total des paires internes au groupe vaut (P² - Q) / 2, et entre deux groupes P1 × P2.
    ~100 groupes au lieu de ~159 millions de paires.
    """
    profile = ["in_satcat", "active", "family", "owner"]
    table = metadata[profile].copy()
    table["w"] = weights.reindex(metadata.index).fillna(0.0).to_numpy()
    table["w2"] = table["w"] ** 2
    groups = table.groupby(profile, as_index=False).agg(P=("w", "sum"), Q=("w2", "sum"))
    groups = groups[groups["P"] > 0].reset_index(drop=True)

    totals = dict.fromkeys(LABELS, 0.0)
    for i, a in groups.iterrows():
        for j in range(i, len(groups)):
            b = groups.loc[j]
            pair_weight = (a["P"] ** 2 - a["Q"]) / 2 if i == j else a["P"] * b["P"]
            totals[classify_pair(a, b)] += pair_weight
    total = sum(totals.values())
    return pd.Series({code: value / total if total else 0.0 for code, value in totals.items()})


def overrepresentation(classified: pd.DataFrame, metadata: pd.DataFrame,
                       presence: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Indices de sur-représentation : part observée / part attendue.

    classified : rapprochements classés, avec une colonne "band" (tranche d'altitude au TCA).
    presence : temps de présence de chaque objet par tranche (altitude.presence_by_band).

    Renvoie :
      - un tableau global : indice "naïf" (toutes les paires du catalogue) et indice corrigé
        de l'altitude (on ne compare que des objets présents dans la même tranche) ;
      - un tableau par tranche d'altitude (indice, nombre observé et nombre attendu).
    """
    total = len(classified)
    observed = classified["category"].value_counts().reindex(list(LABELS), fill_value=0)

    # Indice naïf : chaque objet pèse 1
    naive = expected_shares(metadata, pd.Series(1.0, index=metadata.index))

    # Par tranche : attendu = nombre de rapprochements de la tranche x part attendue dans la tranche
    band_rows, expected_adjusted = [], pd.Series(0.0, index=list(LABELS))
    for band, in_band in classified.dropna(subset=["band"]).groupby("band"):
        band = int(band)  # 400.0 -> 400 : les colonnes de `presence` sont des entiers
        shares = expected_shares(metadata, presence[band])
        expected = shares * len(in_band)
        expected_adjusted += expected
        band_observed = in_band["category"].value_counts().reindex(list(LABELS), fill_value=0)
        for code in LABELS:
            band_rows.append({
                "band": int(band), "category": code,
                "objects": presence[band].sum(),  # objets "présents" en moyenne dans la tranche
                "events": len(in_band),
                "observed": int(band_observed[code]), "expected": expected[code],
                "index": band_observed[code] / expected[code]
                if expected[code] >= MIN_EXPECTED_EVENTS else None,
            })

    global_rows = []
    for code, label in CATEGORIES:
        global_rows.append({
            "catégorie": label,
            "observé": int(observed[code]),
            "part observée (%)": 100 * observed[code] / total,
            "part attendue, naïve (%)": 100 * naive[code],
            "indice naïf": observed[code] / (naive[code] * total)
            if naive[code] * total >= MIN_EXPECTED_EVENTS else None,
            "part attendue, par altitude (%)": 100 * expected_adjusted[code] / total,
            "indice corrigé": observed[code] / expected_adjusted[code]
            if expected_adjusted[code] >= MIN_EXPECTED_EVENTS else None,
        })
    return pd.DataFrame(global_rows), pd.DataFrame(band_rows)


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
