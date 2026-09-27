"""Mise en forme des résultats : tableaux dans le terminal et export CSV."""

import json
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table

from .catalog import SpaceObject

# Au-delà de cet âge, un TLE a pu accumuler plusieurs km d'erreur : on le signale
STALE_TLE_DAYS = 3.0

# Résultats de la dernière détection (écrits par main.py, relus par view.py)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
LAST_RUN_CSV = OUTPUT_DIR / "last_run.csv"
LAST_RUN_INFO = OUTPUT_DIR / "last_run.json"

COLUMNS = [
    "tca_utc", "object_1", "norad_1", "kind_1", "object_2", "norad_2", "kind_2",
    "type", "miss_distance_km", "relative_speed_km_s", "tle_age_days",
]


def build_event_table(events: pd.DataFrame, objects: list[SpaceObject], start: datetime) -> pd.DataFrame:
    """Transforme les événements (indices + secondes) en un tableau lisible, trié par distance.

    tle_age_days : âge du plus vieux des deux TLE au moment du rapprochement.
    Plus il est grand, moins la prédiction est fiable.
    """
    rows = []
    for event in events.itertuples():
        a, b = objects[event.i], objects[event.j]
        tca = start + timedelta(seconds=event.tca_s)
        oldest_epoch = min(a.epoch, b.epoch)
        rows.append({
            "tca_utc": tca,
            "object_1": a.name, "norad_1": a.norad_id, "kind_1": a.kind,
            "object_2": b.name, "norad_2": b.norad_id, "kind_2": b.kind,
            "type": " / ".join(sorted((a.kind, b.kind))),
            "miss_distance_km": event.miss_km,
            "relative_speed_km_s": event.rel_speed_km_s,
            "tle_age_days": (tca - oldest_epoch).total_seconds() / 86400,
        })
    table = pd.DataFrame(rows, columns=COLUMNS)
    return table.sort_values("miss_distance_km").reset_index(drop=True)


def print_funnel(console: Console, rows: list[tuple[str, int]], title: str) -> None:
    """Tableau des étapes de l'entonnoir et du nombre de paires / événements restants."""
    funnel = Table(title=title)
    funnel.add_column("Étape")
    funnel.add_column("Restants", justify="right")
    for label, count in rows:
        funnel.add_row(label, f"{count:,}".replace(",", " "))
    console.print(funnel)


def print_by_type(console: Console, table: pd.DataFrame) -> None:
    """Nombre d'événements par type de paire (débris / satellite, etc.)."""
    by_type = Table(title="Événements par type de paire")
    by_type.add_column("Type")
    by_type.add_column("Événements", justify="right")
    by_type.add_column("dont < 1 km", justify="right")
    by_type.add_column(f"dont TLE > {STALE_TLE_DAYS:.0f} j", justify="right")
    for kind, group in table.groupby("type"):
        by_type.add_row(
            kind,
            str(len(group)),
            str((group["miss_distance_km"] < 1).sum()),
            str((group["tle_age_days"] > STALE_TLE_DAYS).sum()),
        )
    console.print(by_type)


def print_events(console: Console, table: pd.DataFrame, top: int) -> None:
    """Les `top` événements les plus proches. Les TLE trop vieux sont signalés en jaune."""
    events = Table(title=f"Les {min(top, len(table))} rapprochements les plus proches")
    for column in ("TCA (UTC)", "Objet 1", "Objet 2", "Distance", "Vitesse rel.", "Âge TLE"):
        events.add_column(column)
    for row in table.head(top).itertuples():
        age = f"{row.tle_age_days:.1f} j"
        if row.tle_age_days > STALE_TLE_DAYS:
            age = f"[yellow]{age}[/yellow]"
        events.add_row(
            f"{row.tca_utc:%d/%m %H:%M:%S}",
            f"{row.object_1} ({row.norad_1})",
            f"{row.object_2} ({row.norad_2})",
            f"{row.miss_distance_km * 1000:.0f} m",
            f"{row.relative_speed_km_s:.2f} km/s",
            age,
        )
    console.print(events)


def save_last_run(table: pd.DataFrame, info: dict) -> None:
    """Enregistre les résultats de la dernière détection, pour que view.py puisse les réutiliser.

    info : description du calcul (date de début, seuil, durée...), écrite en JSON à côté du CSV.
    """
    export_csv(table, LAST_RUN_CSV)
    LAST_RUN_INFO.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")


def load_last_run() -> tuple[pd.DataFrame, dict]:
    """Relit les résultats enregistrés par save_last_run."""
    if not LAST_RUN_CSV.exists():
        raise FileNotFoundError("Aucune détection enregistrée : lancez d'abord python main.py")
    table = pd.read_csv(LAST_RUN_CSV, dtype={"norad_1": str, "norad_2": str}, encoding="utf-8-sig")
    table["tca_utc"] = pd.to_datetime(table["tca_utc"], utc=True)
    info = json.loads(LAST_RUN_INFO.read_text(encoding="utf-8"))
    return table, info


def export_csv(table: pd.DataFrame, path: Path) -> None:
    """Enregistre tous les événements dans un fichier CSV (lisible par Excel, pandas...).

    L'encodage "utf-8-sig" ajoute une signature en tête de fichier : sans elle,
    Excel ne devine pas l'encodage et affiche "dÃ©bris" au lieu de "débris".
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(path, index=False, float_format="%.4f", date_format="%Y-%m-%dT%H:%M:%S.%fZ",
                 encoding="utf-8-sig")
