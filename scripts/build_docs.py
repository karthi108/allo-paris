"""Build the document corpus for RAG v1 (data/docs.json). See docs/decisions.md D-025.

Sources (licences checked 2026-11-23, recorded in D-025):
- Île-de-France Mobilités, dataset "accessibilite-en-gare" (Licence Ouverte v2.0, Etalab):
  one passage per train / RER station. Downloaded from the portal's JSON export.
- Service Public / DILA fiches (Licence Ouverte 2.0), from the data.gouv.fr dataset
  "Fiches pratiques et ressources de Service-Public.gouv.fr Particuliers" (a ZIP of one XML
  file per fiche). Only the fiches in FICHES are kept, split into passages by chapter.
  Fares are not covered by the assistant, so fare fiches are deliberately left out.

Usage:  python scripts/build_docs.py --fiches-zip PATH_TO_DOWNLOADED_ZIP
The ZIP (~23 MB) is not committed; the output (a few hundred KB) is.
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import urllib.request
import xml.etree.ElementTree as ET  # noqa: S405 (official government XML, 3 small files)
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "docs.json"

IDFM = (
    "https://data.iledefrance-mobilites.fr/api/explore/v2.1/catalog/datasets/accessibilite-en-gare"
)
IDFM_PAGE = "https://data.iledefrance-mobilites.fr/explore/dataset/accessibilite-en-gare/"
LO2 = "https://www.etalab.gouv.fr/wp-content/uploads/2017/04/ETALAB-Licence-Ouverte-v2.0.pdf"
FICHES_DATASET = (
    "https://www.data.gouv.fr/fr/datasets/"
    "fiches-pratiques-et-ressources-de-service-public-gouv-fr-particuliers"
)
# Transport fiches useful for a Paris transport assistant (chosen 2026-11-23)
FICHES = ["F31852", "F12151", "F34049"]
# Parts of a fiche that are navigation, contacts or links, not content
_SKIP = {
    "Theme", "DossierPere", "FilDAriane", "OuSAdresser", "ServiceEnLigne", "VoirAussi",
    "PourEnSavoirPlus", "Reference", "QuiPeutMAider", "Source", "Definition", "Montant",
}  # fmt: skip
MAX_CHARS = 1200
MIN_CHARS = 150


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})  # noqa: S310
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310 (fixed https URLs)
        raw = resp.read()
    # The IDFM export is served gzip-compressed even when not asked for (seen 2026-11-23)
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return json.loads(raw)


def accessibility_docs() -> list[dict[str, Any]]:
    meta = _get_json(IDFM)["metas"]["default"]
    updated = str(meta.get("modified") or "")[:10]
    rows = _get_json(IDFM + "/exports/json")
    docs = []
    for r in rows:
        name = str(r.get("stop_name") or "").strip()
        level = str(r.get("accessibility_level_name") or "").strip()
        if not name or not level:
            continue
        text = f"{name} : {level}."
        if r.get("commentaire"):
            text += " " + str(r["commentaire"]).strip()
        stop_id = str(r.get("stop_point_id") or "")
        docs.append(
            {
                "id": f"idfm-acc-{stop_id.rsplit(':', 1)[-1]}",
                "kind": "accessibility",
                "station_zda": stop_id.rsplit(":", 1)[-1],
                "level": r.get("accessibility_level_id"),
                "title": f"Accessibilité en gare : {name}",
                "text": text,
                "source": "Île-de-France Mobilités, Accessibilité en gare",
                "licence": str(meta.get("license") or "Licence Ouverte v2.0 (Etalab)"),
                "licence_url": LO2,
                "url": IDFM_PAGE,
                "updated": updated,
            }
        )
    return docs


def _text(el: ET.Element) -> str:
    """Readable text of one element (a paragraph or a title), links included as text."""
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


# Headings that start a new passage; their Titre is part of the passage title
_HEADED = {"Situation", "Chapitre", "SousChapitre", "Cas"}


def _units(el: ET.Element, path: tuple[str, ...]) -> list[tuple[tuple[str, ...], str]]:
    """(heading path, paragraph) pairs in document order. A paragraph is read once:
    an Item's text is its Paragraphe; navigation, contacts, links and videos are skipped."""
    out: list[tuple[tuple[str, ...], str]] = []
    for child in el:
        if child.tag in _SKIP or child.tag in ("Titre", "TitreRiche", "Video"):
            continue
        if child.tag in _HEADED:
            head = child.find("Titre")
            name = _text(head) if head is not None else ""
            out += _units(child, path + ((name,) if name else ()))
        elif child.tag == "Paragraphe":
            text = _text(child)
            if text:
                out.append((path, text))
        else:
            out += _units(child, path)
    return out


def _split(text: str) -> list[str]:
    """A paragraph longer than MAX_CHARS, split at sentence ends."""
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for sentence in re.split(r"(?<=[.;:!?])\s+", text):
        if cur and len(cur) + len(sentence) > MAX_CHARS:
            parts.append(cur)
            cur = ""
        cur = f"{cur} {sentence}".strip()
    return parts + ([cur] if cur else [])


def _passages(units: list[tuple[tuple[str, ...], str]]) -> list[tuple[tuple[str, ...], str]]:
    """Group consecutive paragraphs under the same heading path, at most MAX_CHARS each."""
    out: list[tuple[tuple[str, ...], str]] = []
    cur_path: tuple[str, ...] | None = None
    cur = ""
    for path, para in units:
        for piece in _split(para):
            # A very short passage ("Tout dépend de la nature du litige :") introduces what
            # follows: keep it with the next paragraph even under a new heading
            short = len(cur) < MIN_CHARS
            new_head = path != cur_path and not short
            if cur and (new_head or len(cur) + len(piece) > MAX_CHARS):
                out.append((cur_path or (), cur))
                cur = ""
            cur_path = path
            cur = f"{cur} {piece}".strip()
    if cur:
        out.append((cur_path or (), cur))
    return out


def fiche_docs(zip_path: Path) -> list[dict[str, Any]]:
    docs = []
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    with zipfile.ZipFile(zip_path) as z:
        for fid in FICHES:
            root = ET.fromstring(z.read(f"{fid}.xml"))  # noqa: S314 (see import note)
            title = (root.findtext("dc:title", "", ns) or "").strip()
            date = re.search(r"\d{4}-\d{2}-\d{2}", root.findtext("dc:date", "", ns) or "")
            base = {
                "kind": "fiche",
                "fiche": fid,
                "source": "Service Public / DILA",
                "licence": "Licence Ouverte 2.0 (Etalab)",
                "licence_url": LO2,
                "url": root.get("spUrl") or FICHES_DATASET,
                "updated": date.group(0) if date else "",
                "dataset": FICHES_DATASET,
            }
            units: list[tuple[tuple[str, ...], str]] = []
            for part in ("Introduction", "Texte", "ListeSituations"):
                el = root.find(part)
                if el is not None:
                    units += _units(el, ())
            for n, (path, text) in enumerate(_passages(units), start=1):
                docs.append(
                    {
                        **base,
                        "id": f"sp-{fid}-{n}",
                        "title": " · ".join((title, *path)),
                        "text": text,
                    }
                )
    return docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fiches-zip", required=True, type=Path)
    args = ap.parse_args()
    docs = accessibility_docs() + fiche_docs(args.fiches_zip)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"docs": docs}, ensure_ascii=False, indent=1) + "\n", "utf-8")
    kinds: dict[str, int] = {}
    for d in docs:
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KB): {kinds}")


if __name__ == "__main__":
    main()
