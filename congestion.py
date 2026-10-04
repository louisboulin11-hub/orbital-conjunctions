"""Analyse congestion / exposition / pollution de la dernière détection : python congestion.py

Ne refait pas la détection : relit les résultats de la dernière exécution de main.py
(comme view.py), les enrichit avec le SATCAT de CelesTrak, et classe chaque
rapprochement selon les acteurs en présence.

Rappel : une distance nominale inférieure au seuil n'est pas une mesure de risque.
"""

from datetime import datetime

import pandas as pd
from rich.console import Console
from rich.table import Table

from conjunctions.altitude import band_of, density_table, event_altitudes, presence_by_band
from conjunctions.catalog import filter_leo, load_catalog
from conjunctions.fetch import fetch_all
from conjunctions.governance import (
    CATEGORIES,
    LABELS,
    MIN_EXPECTED_EVENTS,
    classify_events,
    exposure_matrix,
    overrepresentation,
    summarize_categories,
)
from conjunctions.report import OUTPUT_DIR
from conjunctions.visualize import plot_exposure
from conjunctions.metadata import build_metadata
from conjunctions.report import load_last_run


def print_summary(console: Console, summary, threshold_km: float) -> None:
    """Tableau récapitulatif des catégories."""
    table = Table(title=f"Rapprochements nominaux à moins de {threshold_km:g} km, par catégorie")
    for column in summary.columns:
        table.add_column(column, justify="left" if column == "catégorie" else "right")
    for _, row in summary.iterrows():
        speed = row["vitesse rel. médiane (km/s)"]
        table.add_row(
            row["catégorie"],
            f"{row['rapprochements']:,}".replace(",", " "),
            f"{row['part (%)']:.1f}",
            str(row["dont < 1 km"]),
            "" if pd.isna(speed) else f"{speed:.1f}",  # catégorie vide : pas de médiane
        )
    console.print(table)


def print_examples(console: Console, classified, per_category: int = 3) -> None:
    """Les rapprochements les plus proches de chaque catégorie, avec les opérateurs en présence."""
    table = Table(title=f"Exemples : les {per_category} plus proches de chaque catégorie")
    for column in ("Catégorie", "Objet 1 (opérateur)", "Objet 2 (opérateur)", "Distance"):
        table.add_column(column)
    for code, label in CATEGORIES:
        closest = classified[classified["category"] == code].nsmallest(per_category, "miss_distance_km")
        for row in closest.itertuples():
            table.add_row(label.split(" (")[0],
                          f"{row.object_1} ({row.operator_1 or row.kind_1})",
                          f"{row.object_2} ({row.operator_2 or row.kind_2})",
                          f"{row.miss_distance_km * 1000:.0f} m")
    console.print(table)


def fmt_index(value) -> str:
    """Indice arrondi, ou "—" s'il n'a pas été calculé (effectif attendu insuffisant)."""
    return "—" if value is None or pd.isna(value) else f"{value:.2f}"


def print_global_index(console: Console, global_index: pd.DataFrame) -> None:
    """Indice de sur-représentation global, naïf et corrigé de l'altitude."""
    table = Table(title="Sur-représentation : part observée / part attendue au hasard")
    for column in ("Catégorie", "Observé", "Part obs.", "Attendu naïf", "Indice naïf",
                   "Attendu par altitude", "Indice corrigé"):
        table.add_column(column, justify="left" if column == "Catégorie" else "right")
    for _, row in global_index.iterrows():
        table.add_row(row["catégorie"], f"{row['observé']:,}".replace(",", " "),
                      f"{row['part observée (%)']:.1f} %", f"{row['part attendue, naïve (%)']:.1f} %",
                      fmt_index(row["indice naïf"]), f"{row['part attendue, par altitude (%)']:.1f} %",
                      fmt_index(row["indice corrigé"]))
    console.print(table)
    console.print(f"Indice > 1 : catégorie plus fréquente que ne le prévoit la composition du "
                  f"catalogue. « — » : moins de {MIN_EXPECTED_EVENTS} rapprochements attendus.")


def print_band_index(console: Console, band_index: pd.DataFrame) -> None:
    """Indice par tranche d'altitude, pour les quatre catégories principales."""
    main_categories = ["intra", "inter", "active_inactive", "inactive_inactive"]
    table = Table(title="Indice corrigé par tranche d'altitude : indice (nombre observé)")
    table.add_column("Tranche")
    table.add_column("Objets", justify="right")
    table.add_column("Rapproch.", justify="right")
    for code in main_categories:
        table.add_column(LABELS[code].split(" (")[0], justify="right")
    for band, rows in band_index.groupby("band"):
        by_code = rows.set_index("category")
        table.add_row(
            f"{band}-{band + 100} km",
            f"{by_code['objects'].iloc[0]:,.0f}".replace(",", " "),
            f"{by_code['events'].iloc[0]:,}".replace(",", " "),
            *[f"{fmt_index(by_code.loc[code, 'index'])} ({by_code.loc[code, 'observed']})"
              for code in main_categories],
        )
    console.print(table)


def print_density(console: Console, density: pd.DataFrame) -> None:
    """Densité d'objets et de rapprochements par tranche d'altitude."""
    table = Table(title="Densité par tranche d'altitude (rapprochements nominaux, ramenés à 24 h)")
    for column in ("Tranche", "Objets", "dont actifs", "dont inactifs", "Densité (/10⁹ km³)",
                   "Rapproch. / jour", "Rapproch. / objet / jour", "Rapport / densité"):
        table.add_column(column, justify="left" if column == "Tranche" else "right")
    for _, row in density.iterrows():
        band = int(row["band"])  # iterrows convertit la ligne en nombres décimaux
        table.add_row(
            f"{band}-{band + 100} km",
            f"{row['objects']:,.0f}".replace(",", " "),
            f"{row['active_objects']:,.0f}".replace(",", " "),
            f"{row['inactive_objects']:,.0f}".replace(",", " "),
            f"{row['density']:.1f}",
            f"{row['events_per_day']:,.0f}".replace(",", " "),
            f"{row['events_per_object_per_day']:.2f}",
            f"{row['pressure_over_density']:.3f}",
        )
    console.print(table)
    console.print("Lecture : si le rapport / densité était à peu près le même d'une tranche à "
                  "l'autre, le nombre de rapprochements par objet croîtrait comme la densité "
                  "(comportement de type « gaz »). La densité est moyennée sur 100 km, alors que "
                  "les couches de Starlink ne font que quelques km d'épaisseur.")


def main() -> None:
    console = Console()
    try:
        events, info = load_last_run()
    except FileNotFoundError as error:
        console.print(f"[yellow]{error}[/yellow]")
        return
    console.print(f"Dernière détection : {datetime.fromisoformat(info['start_utc']):%d/%m %H:%M} UTC, "
                  f"{len(events)} rapprochements à moins de {info['threshold_km']:g} km sur {info['hours']:g} h.")

    with console.status("Lecture du catalogue et du SATCAT..."):
        objects = filter_leo(load_catalog(fetch_all()))
        metadata = build_metadata(objects)
    active = metadata[metadata["active"]]
    console.print(f"Catalogue : {len(metadata)} objets, dont {len(active)} actifs ; "
                  f"{(active['family'] != '').mean():.0%} des actifs rattachés à une famille connue.")

    classified = classify_events(events, metadata)
    print_summary(console, summarize_categories(classified), info["threshold_km"])
    print_examples(console, classified)

    # Normalisation : comparaison avec la part attendue si les objets se croisaient au hasard
    with console.status("Temps de présence par tranche d'altitude et altitude des rapprochements..."):
        presence = presence_by_band(objects, datetime.fromisoformat(info["start_utc"]))
        altitudes = event_altitudes(classified, objects)
        classified["band"] = pd.Series(altitudes).map(
            lambda alt: pd.NA if pd.isna(alt) else int(band_of(alt)))
    with console.status("Calcul des parts attendues..."):
        global_index, band_index = overrepresentation(classified, metadata, presence)
    print_global_index(console, global_index)
    print_band_index(console, band_index)
    print_density(console, density_table(presence, metadata["active"], classified["band"], info["hours"]))

    # Matrice d'exposition opérateur × opérateur (page HTML)
    OUTPUT_DIR.mkdir(exist_ok=True)
    start = datetime.fromisoformat(info["start_utc"])
    plot_exposure(exposure_matrix(classified, metadata, info["hours"]), OUTPUT_DIR / "exposure.html",
                  title_suffix=f", détection du {start:%d/%m/%Y %H:%M} UTC sur {info['hours']:g} h")
    console.print(f"Matrice d'exposition : {OUTPUT_DIR / 'exposure.html'}")

    console.print("Ces catégories décrivent qui se croise de près, pas un niveau de risque : "
                  "les distances sont nominales (TLE précis à ~1 km). Un indice différent de 1 "
                  "peut venir de la géométrie des orbites (même altitude ET même inclinaison au "
                  "sein d'une constellation) et non du comportement des opérateurs ; le modèle "
                  "« au hasard » ignore aussi la vitesse relative. Le catalogue ne contient "
                  "presque ni corps de fusée ni satellites hors service.")


if __name__ == "__main__":
    main()
