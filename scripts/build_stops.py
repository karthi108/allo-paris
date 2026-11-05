"""Build data/stops.json from IDFM open data (run once, then weekly).

Sources (verified 2026-11-05 on data.iledefrance-mobilites.fr):
- arrets-lignes: fields id (IDFM:C01742), shortname, mode, stop_id, stop_name
  stop_id is either IDFM:monomodalStopPlace:<zdaid> (stop area) or IDFM:<arrid> (quay)
- arrets: fields arrid, zdaid, arrtype  (maps quays to stop areas)
- referentiel-des-lignes: id_line, colourweb_hexa, textcolourweb_hexa (line colours)

Output groups everything by stop area (zdaid), which is what PRIM stop-monitoring
accepts as STIF:StopArea:SP:<zdaid>:

Usage:  python scripts/build_stops.py
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.stops import build_index_records  # noqa: E402

BASE = "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets"
MODES = ("Metro", "RapidTransit", "Tramway", "LocalTrain")
OUT = Path(__file__).resolve().parents[1] / "data" / "stops.json"


def _export(dataset: str, select: str, where: str) -> list[dict[str, object]]:
    query = urllib.parse.urlencode({"select": select, "where": where})
    url = f"{BASE}/{dataset}/exports/json?{query}"
    print(f"GET {dataset} ...", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "allo-paris-build/0.1"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=120) as resp:  # noqa: S310
        data: list[dict[str, object]] = json.load(resp)
    print(f"  {len(data)} rows")
    return data


def main() -> None:
    modes = ",".join(f'"{m}"' for m in MODES)
    line_rows = _export(
        "arrets-lignes",
        "id,shortname,mode,stop_id,stop_name,stop_lat,stop_lon",
        f"mode in ({modes})",
    )
    arr_rows = _export("arrets", "arrid,zdaid", 'arrtype in ("metro","rail","tram")')
    color_rows = _export(
        "referentiel-des-lignes",
        "id_line,colourweb_hexa,textcolourweb_hexa",
        'transportmode in ("metro","rail","tram")',
    )
    colors = {
        str(r["id_line"]): (
            str(r.get("colourweb_hexa") or ""),
            str(r.get("textcolourweb_hexa") or ""),
        )
        for r in color_rows
    }
    records = build_index_records(line_rows, arr_rows, colors)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"Wrote {len(records)} stop areas to {OUT}")


if __name__ == "__main__":
    main()
