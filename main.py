"""Point d'entrée du programme : python main.py"""

import time
from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from rich.console import Console
from rich.table import Table
from sgp4.api import SatrecArray

from conjunctions.catalog import EARTH_RADIUS_KM, decode_tle, filter_leo, load_catalog
from conjunctions.fetch import GROUPS, fetch_all
from conjunctions.propagate import iter_time_chunks, propagate, propagate_catalog, teme_to_geodetic

console = Console()


def main() -> None:
    # 1. Télécharger (ou relire en cache) les TLE
    files = fetch_all()
    catalog = load_catalog(files)
    leo = filter_leo(catalog)

    # 2. Résumé : combien d'objets par groupe, et combien en orbite basse
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

    # 3. Exemple : le TLE de l'ISS décodé champ par champ
    iss = next(obj for obj in catalog if obj.norad_id == "25544")
    console.print(f"\n[bold]{iss.name}[/bold]\n{iss.line1}\n{iss.line2}\n")

    fields = Table(title="Décodage du TLE de l'ISS")
    fields.add_column("Champ")
    fields.add_column("Texte brut")
    fields.add_column("Signification")
    for name, raw, meaning in decode_tle(iss.line1, iss.line2):
        fields.add_row(name, raw.strip(), meaning)
    console.print(fields)

    console.print(f"Altitude de l'ISS : entre {iss.perigee_km:.0f} km et {iss.apogee_km:.0f} km")

    # 4. Position de l'ISS maintenant, calculée par SGP4
    now = datetime.now(timezone.utc)
    r, v = propagate(iss.satrec, now)
    lat, lon, alt = teme_to_geodetic(r, now)
    tle_age_h = (now - iss.epoch).total_seconds() / 3600

    console.print(f"\n[bold]Position de l'ISS le {now:%d/%m/%Y à %H:%M:%S} UTC[/bold] (TLE âgé de {tle_age_h:.1f} h)")
    console.print(f"  Repère TEME : x = {r[0]:9.1f} km, y = {r[1]:9.1f} km, z = {r[2]:9.1f} km")
    console.print(f"  Distance au centre de la Terre : {np.linalg.norm(r):.1f} km")
    console.print(f"  Vitesse : {np.linalg.norm(v):.3f} km/s ({np.linalg.norm(v) * 3600:.0f} km/h)")
    console.print(f"  Survole : latitude {lat:.2f}°, longitude {lon:.2f}°, altitude {alt:.1f} km")

    # 5. Trajectoire sur un tour complet (~93 min), un point toutes les 10 minutes
    track = Table(title="Trajectoire de l'ISS sur un tour")
    for column in ("Heure (UTC)", "Latitude", "Longitude", "Altitude"):
        track.add_column(column, justify="right")
    for minutes in range(0, 101, 10):
        t = now + timedelta(minutes=minutes)
        lat, lon, alt = teme_to_geodetic(propagate(iss.satrec, t)[0], t)
        track.add_row(f"{t:%H:%M}", f"{lat:7.2f}°", f"{lon:8.2f}°", f"{alt:.1f} km")
    console.print(track)

    # 6. Tout le catalogue en orbite basse, sur 24 h, une position toutes les 10 s
    satrecs = SatrecArray([obj.satrec for obj in leo])
    failed = np.zeros(len(leo), dtype=bool)  # objets pour lesquels SGP4 a échoué
    n_positions = 0
    chunk_mb = 0.0

    console.print("\n[bold]Propagation de tout le catalogue sur 24 h (pas de 10 s)...[/bold]")
    t0 = time.perf_counter()
    for times_s, r, v, errors in iter_time_chunks(satrecs, now, 24 * 3600, 10, 30 * 60):
        n_positions += r.shape[0] * r.shape[1]
        failed |= (errors != 0).any(axis=1)
        chunk_mb = max(chunk_mb, (r.nbytes + v.nbytes) / 1e6)
    elapsed = time.perf_counter() - t0

    console.print(f"  {n_positions:,} positions calculées en {elapsed:.1f} s".replace(",", " "))
    console.print(f"  Mémoire utilisée par tranche de 30 min : {chunk_mb:.0f} Mo")
    console.print(f"  Objets en erreur (retombés ou orbite invalide) : {failed.sum()}")
    for obj in (o for o, f in zip(leo, failed) if f):
        console.print(f"    - {obj.name} (TLE du {obj.epoch:%d/%m/%Y})")

    # 7. Répartition des altitudes à l'instant présent
    r0, _, _ = propagate_catalog(satrecs, now, np.array([0.0]))
    altitudes = np.linalg.norm(r0[:, 0, :], axis=1) - EARTH_RADIUS_KM
    histogram = Table(title="Nombre d'objets par tranche d'altitude (maintenant)")
    histogram.add_column("Altitude")
    histogram.add_column("Objets", justify="right")
    histogram.add_column("")
    counts, edges = np.histogram(altitudes[~np.isnan(altitudes)], bins=range(200, 2001, 100))
    for count, low in zip(counts, edges):
        bar = "█" * round(40 * count / counts.max())
        histogram.add_row(f"{low:.0f}-{low + 100:.0f} km", str(count), bar)
    console.print(histogram)


if __name__ == "__main__":
    main()
