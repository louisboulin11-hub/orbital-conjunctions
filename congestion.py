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

from conjunctions.catalog import filter_leo, load_catalog
from conjunctions.fetch import fetch_all
from conjunctions.governance import CATEGORIES, classify_events, summarize_categories
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
        metadata = build_metadata(filter_leo(load_catalog(fetch_all())))
    active = metadata[metadata["active"]]
    console.print(f"Catalogue : {len(metadata)} objets, dont {len(active)} actifs ; "
                  f"{(active['family'] != '').mean():.0%} des actifs rattachés à une famille connue.")

    classified = classify_events(events, metadata)
    print_summary(console, summarize_categories(classified), info["threshold_km"])
    print_examples(console, classified)
    console.print("Ces catégories décrivent qui se croise de près, pas un niveau de risque : "
                  "les distances sont nominales (TLE précis à ~1 km).")


if __name__ == "__main__":
    main()
