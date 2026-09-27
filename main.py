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
from conjunctions.propagate import propagate, propagate_catalog, teme_to_geodetic
from conjunctions.screening import (
    CO_ORBITAL_SPEED_KM_S,
    LINEAR_MARGIN_KM,
    coarse_screen,
    coarse_threshold_km,
    count_altitude_overlaps,
    group_events,
    refine_events,
)

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

    # 6. Répartition des altitudes à l'instant présent
    satrecs = SatrecArray([obj.satrec for obj in leo])
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

    # 7. Filtres de l'entonnoir sur 24 h
    threshold_km, step_s = 5.0, 10.0
    radius_km = coarse_threshold_km(threshold_km, step_s)
    console.print(f"\n[bold]Recherche des paires à moins de {threshold_km:.0f} km sur 24 h "
                  f"(pas de {step_s:.0f} s, rayon KD-tree {radius_km:.0f} km)...[/bold]")
    t0 = time.perf_counter()
    result = coarse_screen(leo, now, 24 * 3600, step_s, threshold_km)
    elapsed = time.perf_counter() - t0
    hits = result.hits

    n = len(leo)
    funnel = Table(title=f"Entonnoir de détection ({elapsed:.0f} s de calcul)")
    funnel.add_column("Étape")
    funnel.add_column("Paires restantes", justify="right")
    funnel.add_row("Toutes les paires possibles", f"{n * (n - 1) // 2:,}")
    funnel.add_row("Tranches d'altitude compatibles (pour info)",
                   f"{count_altitude_overlaps(leo, radius_km + 25):,}")
    funnel.add_row(f"KD-tree : à moins de {radius_km:.0f} km à un instant", f"{result.kdtree_pairs:,}")
    funnel.add_row(f"Estimation en ligne droite : moins de {threshold_km + LINEAR_MARGIN_KM:.0f} km",
                   f"{hits.groupby(['i', 'j']).ngroups:,}")
    console.print(funnel)

    # 8. Raffinement : regroupement en événements, puis TCA et distance exacts
    t0 = time.perf_counter()
    events = refine_events(group_events(hits, step_s), leo, now, step_s)
    elapsed = time.perf_counter() - t0
    co_orbital = events["rel_speed_km_s"] < CO_ORBITAL_SPEED_KM_S
    crossings = events[~co_orbital]
    risky = crossings[crossings["miss_km"] < threshold_km].copy()
    risky["type"] = [" / ".join(sorted((leo[i].kind, leo[j].kind))) for i, j in zip(risky["i"], risky["j"])]

    summary = Table(title=f"Raffinement ({elapsed:.0f} s de calcul)")
    summary.add_column("Étape")
    summary.add_column("Événements", justify="right")
    summary.add_row("Touches regroupées en événements", f"{len(events):,}")
    summary.add_row(f"Vol groupé écarté (vitesse relative < {CO_ORBITAL_SPEED_KM_S * 1000:.0f} m/s)",
                    f"{co_orbital.sum():,}")
    summary.add_row(f"[bold]Croisements à moins de {threshold_km:.0f} km (distance exacte)",
                    f"[bold]{len(risky):,}")
    console.print(summary)

    by_type = Table(title=f"Croisements à moins de {threshold_km:.0f} km, par type de paire")
    by_type.add_column("Type")
    by_type.add_column("Événements", justify="right")
    by_type.add_column("dont < 1 km", justify="right")
    for kind, group in risky.groupby("type"):
        by_type.add_row(kind, f"{len(group):,}", f"{(group['miss_km'] < 1).sum():,}")
    console.print(by_type)

    closest = Table(title="Les 15 croisements les plus proches")
    for column in ("TCA (UTC)", "Objet 1", "Objet 2", "Distance", "Vitesse relative"):
        closest.add_column(column)
    for row in risky.nsmallest(15, "miss_km").itertuples():
        tca = now + timedelta(seconds=row.tca_s)
        closest.add_row(f"{tca:%d/%m %H:%M:%S}", leo[row.i].name, leo[row.j].name,
                        f"{row.miss_km * 1000:.0f} m", f"{row.rel_speed_km_s:.2f} km/s")
    console.print(closest)


if __name__ == "__main__":
    main()
