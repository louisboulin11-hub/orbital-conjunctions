"""Vues 3D des résultats, à jour à l'instant présent (quelques secondes).

Utilisation : python view.py [options]      (python view.py --help pour la liste)

Ne refait pas la détection : relit les résultats de la dernière exécution de
main.py, recalcule la position actuelle des objets, et génère les pages HTML.
"""

import argparse
from datetime import datetime, timezone

from rich.console import Console

from conjunctions.catalog import filter_leo, load_catalog
from conjunctions.fetch import fetch_all
from conjunctions.report import OUTPUT_DIR, load_last_run
from conjunctions.visualize import plot_event, plot_overview

# Au-delà, les résultats commencent à dater : on suggère de relancer la détection
STALE_RUN_HOURS = 12


def parse_args() -> argparse.Namespace:
    """Lit les options passées en ligne de commande."""
    parser = argparse.ArgumentParser(description="Génère les vues 3D à partir de la dernière détection.")
    parser.add_argument("--debris-only", action="store_true",
                        help="ne montrer que les rapprochements impliquant au moins un débris")
    parser.add_argument("--event", type=int, default=1,
                        help="rang du rapprochement à détailler parmi ceux à venir (défaut : 1, le plus proche)")
    parser.add_argument("--markers", type=int, default=20,
                        help="nombre de rapprochements marqués dans la vue d'ensemble (défaut : 20)")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    console = Console()
    now = datetime.now(timezone.utc)

    try:
        table, info = load_last_run()
    except FileNotFoundError as error:
        console.print(f"[yellow]{error}[/yellow]")
        return
    run_start = datetime.fromisoformat(info["start_utc"])
    run_age_h = (now - run_start).total_seconds() / 3600
    console.print(f"Dernière détection : {run_start:%d/%m %H:%M} UTC (il y a {run_age_h:.1f} h), "
                  f"seuil {info['threshold_km']:g} km sur {info['hours']:g} h.")
    if run_age_h > STALE_RUN_HOURS:
        console.print(f"[yellow]Ces résultats ont plus de {STALE_RUN_HOURS} h : "
                      "pensez à relancer python main.py.[/yellow]")

    # Seuls les rapprochements encore à venir ont un intérêt
    upcoming = table[table["tca_utc"] > now]
    if args.debris_only:
        upcoming = upcoming[upcoming["type"].str.contains("débris")]
    console.print(f"{len(upcoming)} rapprochements à venir sur {len(table)} détectés.")
    if upcoming.empty:
        console.print("[yellow]Rien à afficher : relancez python main.py.[/yellow]")
        return

    # Les TLE ont pu être mis à jour depuis la détection : un objet retombé dans
    # l'atmosphère peut avoir disparu du catalogue. On écarte ses rapprochements.
    leo = filter_leo(load_catalog(fetch_all()))
    known = {obj.norad_id for obj in leo}
    upcoming = upcoming[upcoming["norad_1"].isin(known) & upcoming["norad_2"].isin(known)]
    if upcoming.empty:
        console.print("[yellow]Rien à afficher : relancez python main.py.[/yellow]")
        return
    rank = min(max(args.event, 1), len(upcoming))
    event = upcoming.iloc[rank - 1]

    OUTPUT_DIR.mkdir(exist_ok=True)
    with console.status("Génération des vues 3D..."):
        plot_overview(leo, now, upcoming, OUTPUT_DIR / "overview.html", n_events=args.markers)
        plot_event(leo, event, OUTPUT_DIR / "event.html")

    console.print(f"Vue d'ensemble (positions du {now:%d/%m %H:%M:%S} UTC) : {OUTPUT_DIR / 'overview.html'}")
    console.print(f"Rapprochement n° {rank} : {event['object_1']} / {event['object_2']}, "
                  f"{event['miss_distance_km'] * 1000:.0f} m le {event['tca_utc']:%d/%m %H:%M} UTC : "
                  f"{OUTPUT_DIR / 'event.html'}")


if __name__ == "__main__":
    main()
