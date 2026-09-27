"""Détecteur de rapprochements orbitaux (calcul long : quelques minutes).

Utilisation : python main.py [options]      (python main.py --help pour la liste)
Les résultats sont enregistrés dans output/ ; les vues 3D se génèrent ensuite avec view.py.
"""

import argparse
import time
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from conjunctions.catalog import filter_leo, load_catalog
from conjunctions.fetch import fetch_all
from conjunctions.report import (
    LAST_RUN_CSV,
    build_event_table,
    export_csv,
    print_by_type,
    print_events,
    print_funnel,
    save_last_run,
)
from conjunctions.screening import (
    CO_ORBITAL_SPEED_KM_S,
    LINEAR_MARGIN_KM,
    coarse_screen,
    coarse_threshold_km,
    count_altitude_overlaps,
    group_events,
    refine_events,
)


def parse_args() -> argparse.Namespace:
    """Lit les options passées en ligne de commande."""
    parser = argparse.ArgumentParser(
        description="Détecte les rapprochements entre satellites et débris en orbite basse, "
        "à partir des TLE publics de CelesTrak."
    )
    parser.add_argument("--threshold", type=float, default=5.0,
                        help="distance d'alerte en km (défaut : 5)")
    parser.add_argument("--hours", type=float, default=24.0,
                        help="durée de la fenêtre de prédiction en heures (défaut : 24)")
    parser.add_argument("--step", type=float, default=10.0,
                        help="pas de la grille de temps en secondes (défaut : 10)")
    parser.add_argument("--debris-only", action="store_true",
                        help="n'afficher que les rapprochements impliquant au moins un débris")
    parser.add_argument("--top", type=int, default=15,
                        help="nombre de rapprochements à afficher (défaut : 15)")
    parser.add_argument("--csv", type=Path,
                        help="exporter tous les rapprochements dans ce fichier CSV")
    parser.add_argument("--refresh", action="store_true",
                        help="re-télécharger les TLE même si la copie locale a moins de 2 h")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    start = datetime.now(timezone.utc)

    # 1. Données : TLE de CelesTrak, limités à l'orbite basse
    with console.status("Lecture des TLE..."):
        leo = filter_leo(load_catalog(fetch_all(force=args.refresh)))
    console.print(f"{len(leo):,} objets en orbite basse. Recherche des rapprochements à moins de "
                  f"{args.threshold:g} km entre le {start:%d/%m %H:%M} et +{args.hours:g} h (UTC).")

    # 2. Filtre grossier (KD-tree + estimation en ligne droite), puis raffinement
    t0 = time.perf_counter()
    with console.status("Filtre grossier (quelques minutes)..."):
        screening = coarse_screen(leo, start, args.hours * 3600, args.step, args.threshold)
    with console.status("Raffinement..."):
        events = refine_events(group_events(screening.hits, args.step), leo, start, args.step)
    elapsed = time.perf_counter() - t0

    # 3. Tri : on écarte le vol groupé et on applique le seuil sur la distance exacte
    co_orbital = events["rel_speed_km_s"] < CO_ORBITAL_SPEED_KM_S
    crossings = events[~co_orbital & (events["miss_km"] < args.threshold)]
    all_events = build_event_table(crossings, leo, start)

    # 4. Enregistrement systématique de tous les résultats, pour view.py
    save_last_run(all_events, {
        "start_utc": start.isoformat(),
        "hours": args.hours,
        "threshold_km": args.threshold,
        "step_s": args.step,
        "objects": len(leo),
    })

    table = all_events
    if args.debris_only:
        table = table[table["type"].str.contains("débris")]

    # 5. Affichage
    n = len(leo)
    radius_km = coarse_threshold_km(args.threshold, args.step)
    print_funnel(console, [
        ("Paires possibles", n * (n - 1) // 2),
        ("Tranches d'altitude compatibles (pour info)", count_altitude_overlaps(leo, radius_km + 25)),
        (f"KD-tree : paires à moins de {radius_km:g} km à un instant", screening.kdtree_pairs),
        (f"Ligne droite : paires à moins de {args.threshold + LINEAR_MARGIN_KM:g} km",
         screening.hits.groupby(["i", "j"]).ngroups),
        ("Événements (une paire peut se croiser plusieurs fois)", len(events)),
        (f"Vol groupé écarté (< {CO_ORBITAL_SPEED_KM_S * 1000:g} m/s)", int(co_orbital.sum())),
        (f"Rapprochements à moins de {args.threshold:g} km", len(crossings)),
    ], title=f"Entonnoir de détection ({elapsed:.0f} s de calcul)")
    if args.debris_only:
        console.print(f"Filtre --debris-only : {len(table)} rapprochements impliquent un débris.")

    if table.empty:
        console.print("[green]Aucun rapprochement sous le seuil sur la période.[/green]")
    else:
        print_by_type(console, table)
        print_events(console, table, args.top)

    if args.csv:
        export_csv(table, args.csv)
        console.print(f"{len(table)} rapprochements exportés dans {args.csv}")

    console.print(f"Résultats enregistrés dans {LAST_RUN_CSV}. "
                  "Pour les vues 3D : python view.py")


if __name__ == "__main__":
    main()
