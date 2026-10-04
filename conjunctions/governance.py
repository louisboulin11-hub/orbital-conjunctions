"""Classement des rapprochements selon les acteurs en présence (congestion, exposition, pollution).

Rappel : une distance nominale sous le seuil n'est PAS une mesure de risque (TLE précis
à ~1 km, manœuvres autonomes de certaines constellations). Ce classement décrit QUI se
croise de près, pas qui court un danger.
"""

from dataclasses import dataclass

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


# Regroupements pour la matrice d'exposition (94 opérateurs distincts seraient illisibles)
TOP_FAMILIES = 8
OTHER_FAMILIES = "Autres familles identifiées"
UNIDENTIFIED_BY_COUNTRY = {
    "PRC": "Non identifiés : Chine",
    "US": "Non identifiés : États-Unis",
    "CIS": "Non identifiés : CEI / Russie",
    "TBD": "Non identifiés : propriétaire non déterminé",
}
OTHER_UNIDENTIFIED = "Non identifiés : autres pays"
DEBRIS_GROUP = "Débris et objets inactifs"


@dataclass
class ExposureMatrix:
    """Matrices d'exposition entre groupes d'opérateurs (rapprochements nominaux)."""

    order: list[str]  # ordre des lignes et des colonnes
    single_families: list[str]  # groupes réduits à une seule famille (diagonale = intra)
    per_day: pd.DataFrame  # rapprochements / jour hors intra-constellation, symétrique
    intra_per_day: pd.Series  # rapprochements intra-constellation / jour, par groupe
    satellites: pd.Series  # nombre de satellites actifs par groupe
    per_satellite: pd.DataFrame  # per_day ÷ satellites de la ligne (lignes : groupes actifs)


def operator_groups(classified: pd.DataFrame, metadata: pd.DataFrame,
                    top_n: int = TOP_FAMILIES) -> tuple[pd.Series, list[str], list[str]]:
    """Rattache chaque objet à un groupe de la matrice.

    Les top_n familles les plus présentes dans les rapprochements hors intra-constellation
    gardent leur propre ligne ; les autres familles sont regroupées ; les satellites non
    identifiés sont regroupés par pays ; tous les objets inactifs forment la ligne "débris".
    Renvoie (groupe de chaque objet, ordre d'affichage, familles gardées seules).
    """
    non_intra = classified[classified["category"] != "intra"]
    families = pd.concat([metadata["family"].reindex(non_intra["norad_1"]),
                          metadata["family"].reindex(non_intra["norad_2"])])
    top = list(families[families.fillna("") != ""].value_counts().head(top_n).index)

    def group_of(row: pd.Series) -> str:
        if not row["active"]:
            return DEBRIS_GROUP
        if row["family"] in top:
            return row["family"]
        if row["family"]:
            return OTHER_FAMILIES
        return UNIDENTIFIED_BY_COUNTRY.get(row["owner"], OTHER_UNIDENTIFIED)

    groups = metadata.apply(group_of, axis=1)
    order = top + [OTHER_FAMILIES, *UNIDENTIFIED_BY_COUNTRY.values(), OTHER_UNIDENTIFIED, DEBRIS_GROUP]
    return groups, order, top


def exposure_matrix(classified: pd.DataFrame, metadata: pd.DataFrame, hours: float) -> ExposureMatrix:
    """Construit les matrices d'exposition groupe × groupe.

    Les rapprochements intra-constellation sont mis à part : ce n'est pas de l'exposition
    entre acteurs. Ils sont gardés dans intra_per_day pour être affichés sur la diagonale.
    """
    groups, order, single = operator_groups(classified, metadata)
    g1 = groups.reindex(classified["norad_1"]).to_numpy()
    g2 = groups.reindex(classified["norad_2"]).to_numpy()
    sides = pd.DataFrame({"g1": g1, "g2": g2, "category": classified["category"].to_numpy()}).dropna()
    scale = 24 / hours  # ramène à une journée

    intra = sides[sides["category"] == "intra"]
    intra_per_day = intra["g1"].value_counts().reindex(order, fill_value=0) * scale

    # Tableau croisé (ligne = groupe de l'objet 1, colonne = groupe de l'objet 2), puis
    # symétrisation : un rapprochement A-B compte dans la case (A, B) et dans la case (B, A).
    other = sides[sides["category"] != "intra"]
    counts = pd.crosstab(other["g1"], other["g2"]).reindex(index=order, columns=order, fill_value=0)
    symmetric = counts + counts.T
    for g in order:  # la diagonale a été comptée deux fois
        symmetric.loc[g, g] = counts.loc[g, g]
    per_day = symmetric * scale

    satellites = groups[metadata["active"]].value_counts().reindex(order, fill_value=0)
    active_rows = [g for g in order if g != DEBRIS_GROUP]
    per_satellite = per_day.loc[active_rows].div(satellites.loc[active_rows], axis=0)
    return ExposureMatrix(order, single, per_day, intra_per_day, satellites, per_satellite)


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
