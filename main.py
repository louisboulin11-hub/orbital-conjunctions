"""Point d'entrée du programme : python main.py"""

from collections import Counter
from datetime import datetime, timedelta, timezone

import numpy as np
from rich.console import Console
from rich.table import Table

from conjunctions.catalog import decode_tle, filter_leo, load_catalog
from conjunctions.fetch import GROUPS, fetch_all
from conjunctions.propagate import propagate, teme_to_geodetic

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


if __name__ == "__main__":
    main()
