"""Rétro-validation sur des collisions réelles : python backtest.py

Question posée : avec les TLE publiés AVANT une collision réelle, notre détection
aurait-elle signalé le danger ? Pour chaque collision, on rejoue la détection avec
l'information disponible 3 jours, 2 jours, 1 jour et quelques heures avant l'impact.

Nécessite un compte Space-Track (voir conjunctions/history.py).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
from rich.console import Console
from rich.table import Table

from conjunctions.catalog import SpaceObject
from conjunctions.history import fetch_history, read_history
from conjunctions.screening import coarse_screen, group_events, refine_events

THRESHOLD_KM = 5.0  # seuil d'alerte, le même que main.py
REPORT_KM = 100.0  # on calcule jusqu'à 100 km pour chiffrer aussi un rapprochement NON détecté
STEP_S = 10.0
LEAD_DAYS = [3, 2, 1, 0]  # ancienneté de l'information : TLE d'époque antérieure de N jours à la référence


@dataclass
class Case:
    """Une collision réelle à rejouer."""

    name: str
    norad_ids: tuple[str, str]
    window_start: datetime  # début de la fenêtre de recherche de 24 h
    collision: datetime | None  # instant connu de la collision (None si seule la date est connue)

    @property
    def reference(self) -> datetime:
        """Instant de référence : on ne s'autorise que des TLE d'époque antérieure."""
        return self.collision or self.window_start


CASES = [
    Case(
        name="Iridium 33 / Cosmos 2251 (10/02/2009)",
        norad_ids=("24946", "22675"),
        window_start=datetime(2009, 2, 10, 4, 56, tzinfo=timezone.utc),  # 12 h avant l'impact
        collision=datetime(2009, 2, 10, 16, 55, 59, 806000, tzinfo=timezone.utc),
    ),
    Case(
        name="CERISE / fragment d'Ariane 1 (24/07/1996)",
        norad_ids=("23606", "18208"),
        window_start=datetime(1996, 7, 24, tzinfo=timezone.utc),  # heure inconnue : toute la journée
        collision=None,
    ),
]


def latest_before(elsets: list[SpaceObject], norad_id: str, cutoff: datetime) -> SpaceObject | None:
    """Le TLE le plus récent d'un objet dont l'époque précède `cutoff`."""
    candidates = [e for e in elsets if e.norad_id == norad_id and e.epoch < cutoff]
    return candidates[-1] if candidates else None  # la liste est triée par époque


def closest_approach(a: SpaceObject, b: SpaceObject, start: datetime) -> pd.Series | None:
    """Le rapprochement le plus proche entre a et b sur 24 h, avec le pipeline de main.py."""
    screening = coarse_screen([a, b], start, 24 * 3600, STEP_S, REPORT_KM)
    if screening.hits.empty:
        return None
    events = refine_events(group_events(screening.hits, STEP_S), [a, b], start, STEP_S)
    return events.loc[events["miss_km"].idxmin()]


def run_case(console: Console, case: Case) -> None:
    """Rejoue une collision avec des TLE de plus en plus récents, et affiche le résultat."""
    path = fetch_history(list(case.norad_ids), case.reference - timedelta(days=10), case.reference)
    elsets = read_history(path)
    id_a, id_b = case.norad_ids

    table = Table(title=case.name)
    for column in ("Information du", "Âge des TLE", "TCA prévu (UTC)", "Écart / impact",
                   "Distance prévue", "Vitesse rel.", f"Alerte < {THRESHOLD_KM:g} km"):
        table.add_column(column, justify="right")

    for lead in LEAD_DAYS:
        cutoff = case.reference - timedelta(days=lead)
        a, b = latest_before(elsets, id_a, cutoff), latest_before(elsets, id_b, cutoff)
        label = f"{cutoff:%d/%m %H:%M}" + (f" (J-{lead})" if lead else " (dernier)")
        if a is None or b is None:
            table.add_row(label, "TLE manquant", "", "", "", "", "")
            continue

        ages = [(case.reference - e.epoch).total_seconds() / 3600 for e in (a, b)]
        event = closest_approach(a, b, case.window_start)
        if event is None:
            table.add_row(label, f"{ages[0]:.0f} h / {ages[1]:.0f} h", "—", "",
                          f"> {REPORT_KM:g} km", "", "[red]non")
            continue

        tca = case.window_start + timedelta(seconds=float(event["tca_s"]))
        offset = f"{(tca - case.collision).total_seconds():+.1f} s" if case.collision else "?"
        detected = event["miss_km"] < THRESHOLD_KM
        table.add_row(
            label,
            f"{ages[0]:.0f} h / {ages[1]:.0f} h",
            f"{tca:%d/%m %H:%M:%S}",
            offset,
            f"{event['miss_km'] * 1000:,.0f} m".replace(",", " "),
            f"{event['rel_speed_km_s']:.2f} km/s",
            "[green]OUI" if detected else "[red]non",
        )
    console.print(table)
    names = {e.norad_id: e.name for e in elsets}
    console.print(f"  Objets : {names.get(id_a, id_a)} ({id_a}) et {names.get(id_b, id_b)} ({id_b}). "
                  f"Âge des TLE mesuré à {'la collision' if case.collision else 'minuit le jour J'}.\n")


def main() -> None:
    console = Console()
    for case in CASES:
        try:
            run_case(console, case)
        except RuntimeError as error:
            console.print(f"[yellow]{case.name} : {error}[/yellow]")


if __name__ == "__main__":
    main()
