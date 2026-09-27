"""Point d'entrée du programme : python main.py"""

from collections import Counter

from rich.console import Console
from rich.table import Table

from conjunctions.catalog import decode_tle, filter_leo, load_catalog
from conjunctions.fetch import GROUPS, fetch_all

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


if __name__ == "__main__":
    main()
