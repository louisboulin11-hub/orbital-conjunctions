"""Démonstration pas à pas : python demo.py

Montre les briques de base du projet sur des exemples concrets :
contenu du catalogue, décodage d'un TLE, position de l'ISS calculée par SGP4,
et répartition des objets en altitude.
"""

from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from rich.console import Console
from rich.table import Table
from sgp4.api import SatrecArray

from conjunctions.catalog import EARTH_RADIUS_KM, SpaceObject, decode_tle, filter_leo, load_catalog
from conjunctions.fetch import GROUPS, fetch_all
from conjunctions.propagate import propagate, propagate_catalog, teme_to_geodetic

console = Console()


def show_catalog(catalog: list[SpaceObject], leo: list[SpaceObject]) -> None:
    """Nombre d'objets par groupe, et combien sont en orbite basse."""
    total_by_group = Counter(obj.group for obj in catalog)
    leo_by_group = Counter(obj.group for obj in leo)

    table = Table(title="Catalogue téléchargé depuis CelesTrak")
    table.add_column("Groupe")
    table.add_column("Objets", justify="right")
    table.add_column("dont orbite basse", justify="right")
    for group, description in GROUPS.items():
        table.add_row(description, str(total_by_group[group]), str(leo_by_group[group]))
    table.add_row("[bold]Total", f"[bold]{len(catalog)}", f"[bold]{len(leo)}")
    console.print(table)


def show_tle(obj: SpaceObject) -> None:
    """Un TLE décodé champ par champ."""
    console.print(f"\n[bold]{obj.name}[/bold]\n{obj.line1}\n{obj.line2}\n")
    fields = Table(title=f"Décodage du TLE de {obj.name}")
    fields.add_column("Champ")
    fields.add_column("Texte brut")
    fields.add_column("Signification")
    for name, raw, meaning in decode_tle(obj.line1, obj.line2):
        fields.add_row(name, raw.strip(), meaning)
    console.print(fields)
    console.print(f"Altitude : entre {obj.perigee_km:.0f} km et {obj.apogee_km:.0f} km")


def show_position(obj: SpaceObject, now: datetime) -> None:
    """Position actuelle d'un objet, puis sa trajectoire sur un tour (~100 min)."""
    r, v = propagate(obj.satrec, now)
    lat, lon, alt = teme_to_geodetic(r, now)
    tle_age_h = (now - obj.epoch).total_seconds() / 3600

    console.print(f"\n[bold]Position de {obj.name} le {now:%d/%m/%Y à %H:%M:%S} UTC[/bold] "
                  f"(TLE âgé de {tle_age_h:.1f} h)")
    console.print(f"  Repère TEME : x = {r[0]:9.1f} km, y = {r[1]:9.1f} km, z = {r[2]:9.1f} km")
    console.print(f"  Distance au centre de la Terre : {np.linalg.norm(r):.1f} km")
    console.print(f"  Vitesse : {np.linalg.norm(v):.3f} km/s ({np.linalg.norm(v) * 3600:.0f} km/h)")
    console.print(f"  Survole : latitude {lat:.2f}°, longitude {lon:.2f}°, altitude {alt:.1f} km")

    track = Table(title=f"Trajectoire de {obj.name} sur un tour")
    for column in ("Heure (UTC)", "Latitude", "Longitude", "Altitude"):
        track.add_column(column, justify="right")
    for minutes in range(0, 101, 10):
        t = now + timedelta(minutes=minutes)
        lat, lon, alt = teme_to_geodetic(propagate(obj.satrec, t)[0], t)
        track.add_row(f"{t:%H:%M}", f"{lat:7.2f}°", f"{lon:8.2f}°", f"{alt:.1f} km")
    console.print(track)


def show_altitudes(leo: list[SpaceObject], now: datetime) -> None:
    """Histogramme du nombre d'objets par tranche d'altitude de 100 km."""
    r, _, _ = propagate_catalog(SatrecArray([obj.satrec for obj in leo]), now, np.array([0.0]))
    altitudes = np.linalg.norm(r[:, 0, :], axis=1) - EARTH_RADIUS_KM
    counts, edges = np.histogram(altitudes[~np.isnan(altitudes)], bins=range(200, 2001, 100))

    histogram = Table(title="Nombre d'objets par tranche d'altitude (maintenant)")
    histogram.add_column("Altitude")
    histogram.add_column("Objets", justify="right")
    histogram.add_column("")
    for count, low in zip(counts, edges):
        histogram.add_row(f"{low:.0f}-{low + 100:.0f} km", str(count), "█" * round(40 * count / counts.max()))
    console.print(histogram)


def main() -> None:
    catalog = load_catalog(fetch_all())
    leo = filter_leo(catalog)
    iss = next(obj for obj in catalog if obj.norad_id == "25544")
    now = datetime.now(timezone.utc)

    show_catalog(catalog, leo)
    show_tle(iss)
    show_position(iss, now)
    show_altitudes(leo, now)


if __name__ == "__main__":
    main()
