"""Historique des analyses de congestion, pour suivre leur évolution dans le temps.

Trois sorties, dans output/history/ :
  - congestion_history.csv        une ligne par détection analysée (chiffres clés)
  - congestion_history_bands.csv  une ligne par détection et par tranche d'altitude
  - runs/                         copie datée des rapprochements bruts de chaque détection,
                                  pour pouvoir refaire les analyses avec une méthode améliorée

Une même détection analysée deux fois remplace sa ligne au lieu de s'ajouter : sinon,
une journée compterait double dans une tendance.
"""

import json
from datetime import datetime, timezone

import pandas as pd

from .governance import CATEGORIES
from .report import OUTPUT_DIR, export_csv

HISTORY_DIR = OUTPUT_DIR / "history"
HISTORY_CSV = HISTORY_DIR / "congestion_history.csv"
BANDS_CSV = HISTORY_DIR / "congestion_history_bands.csv"
RAW_DIR = HISTORY_DIR / "runs"

# À incrémenter quand la méthode change (liste des familles, règles de classement...) :
# une évolution dans le temps pourrait sinon venir du changement de méthode, pas de la réalité.
METHOD_VERSION = 1

KEY = "detection_start_utc"


def history_row(info: dict, metadata: pd.DataFrame, global_index: pd.DataFrame,
                density: pd.DataFrame) -> dict:
    """Les chiffres clés d'une analyse, à plat, pour une ligne de l'historique."""
    active = metadata[metadata["active"]]
    now = datetime.now(timezone.utc)
    row = {
        KEY: info["start_utc"],
        "analysis_utc": now.isoformat(timespec="seconds"),
        # Délai entre détection et analyse : au-delà de quelques heures, le catalogue utilisé
        # pour l'analyse n'est plus exactement celui de la détection
        "analysis_delay_h": round((now - datetime.fromisoformat(info["start_utc"])).total_seconds() / 3600, 1),
        "method_version": METHOD_VERSION,
        "threshold_km": info["threshold_km"],
        "hours": info["hours"],
        "step_s": info["step_s"],
        "objects": len(metadata),
        "active": len(active),
        "inactive": len(metadata) - len(active),
        "starlink": int((active["family"] == "Starlink (SpaceX)").sum()),
        "identified_share": float((active["family"] != "").mean()),
        "events_total": int(global_index["observé"].sum()),
    }
    # global_index suit l'ordre de CATEGORIES : on associe chaque ligne à son code
    for (code, _), (_, values) in zip(CATEGORIES, global_index.iterrows()):
        row[f"n_{code}"] = int(values["observé"])
        row[f"share_{code}"] = values["part observée (%)"] / 100
        row[f"index_naive_{code}"] = values["indice naïf"]
        row[f"index_adjusted_{code}"] = values["indice corrigé"]
    shell = density[density["band"] == 400]  # la tranche la plus dense, celle de Starlink
    if not shell.empty:
        row["objects_400_500"] = shell["objects"].iloc[0]
        row["density_400_500"] = shell["density"].iloc[0]
        row["events_per_object_400_500"] = shell["events_per_object_per_day"].iloc[0]
    return row


def upsert(path, rows: pd.DataFrame) -> None:
    """Ajoute des lignes au fichier, en remplaçant celles de la même détection."""
    if path.exists():
        existing = pd.read_csv(path, encoding="utf-8-sig")
        existing = existing[~existing[KEY].isin(rows[KEY])]
        rows = pd.concat([existing, rows], ignore_index=True)
    rows.sort_values(KEY).to_csv(path, index=False, encoding="utf-8-sig")


def raw_name(start_utc: str) -> str:
    """Nom de fichier daté et sans caractères interdits : 2026-10-04T20-30-00Z."""
    start = datetime.fromisoformat(start_utc).astimezone(timezone.utc)
    return start.strftime("%Y-%m-%dT%H-%M-%SZ")


def save_history(events: pd.DataFrame, info: dict, metadata: pd.DataFrame,
                 global_index: pd.DataFrame, density: pd.DataFrame) -> None:
    """Enregistre l'analyse dans l'historique et archive les rapprochements bruts.

    On archive les rapprochements ANALYSÉS (déjà en mémoire), pas le fichier last_run.csv :
    une nouvelle détection a pu le remplacer pendant l'analyse.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    upsert(HISTORY_CSV, pd.DataFrame([history_row(info, metadata, global_index, density)]))

    bands = density.copy()
    bands.insert(0, KEY, info["start_utc"])
    bands.insert(1, "method_version", METHOD_VERSION)
    upsert(BANDS_CSV, bands)

    name = raw_name(info["start_utc"])
    export_csv(events, RAW_DIR / f"{name}_events.csv")
    (RAW_DIR / f"{name}_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")


def load_history() -> pd.DataFrame:
    """L'historique complet (vide si aucune analyse n'a encore été enregistrée)."""
    if not HISTORY_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(HISTORY_CSV, encoding="utf-8-sig")
