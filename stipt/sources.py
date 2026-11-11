"""Ophalen van Infrabel Open Data.

Twee bronnen:
- het dagbestand (D-1): elke ochtend overschreven met de ritten van gisteren
- de maandbestanden: de definitieve ruwe data per maand, sinds januari 2014

De structuur van de maandbestanden-dataset is niet gedocumenteerd tot op het
niveau van veldnamen, dus we zoeken de downloadlinks robuust op: elke URL in
een record die naar een .csv of .zip wijst, met een maand in de naam of velden.
"""

from __future__ import annotations

import io
import re
import shutil
import zipfile
from pathlib import Path
from typing import Iterator

import requests

from . import config

_MONTH_RE = re.compile(r"(20\d{2})[-_ ]?(0[1-9]|1[0-2])")


def _get(url: str, *, stream: bool = False, params: dict | None = None) -> requests.Response:
    r = requests.get(
        url,
        params=params,
        headers={"User-Agent": config.USER_AGENT},
        timeout=600,
        stream=stream,
    )
    r.raise_for_status()
    return r


def _download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _get(url, stream=True) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r.raw, f, length=1 << 20)
    tmp.replace(dest)
    return dest


def download_daily(dest_dir: Path = config.RAW / "daily") -> Path:
    """Het volledige D-1 bestand als CSV (puntkomma, technische kolomnamen)."""
    url = f"{config.API}/{config.DS_DAILY}/exports/csv"
    dest = dest_dir / "d-1.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with _get(url, stream=True, params={"delimiter": ";", "use_labels": "false"}) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r.raw, f, length=1 << 20)
    return dest


def _records(dataset: str) -> Iterator[dict]:
    """Alle records van een (kleine) dataset, met paginering."""
    offset, limit = 0, 100
    while True:
        r = _get(
            f"{config.API}/{dataset}/records",
            params={"limit": limit, "offset": offset},
        ).json()
        rows = r.get("results", [])
        yield from rows
        offset += len(rows)
        if not rows or offset >= r.get("total_count", 0):
            break


def _walk(value, found: list[str]) -> None:
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "url" and isinstance(v, str):
                found.append(v)
            else:
                _walk(v, found)
    elif isinstance(value, list):
        for v in value:
            _walk(v, found)
    elif isinstance(value, str) and value.startswith("http"):
        found.append(value)


def list_monthly_files() -> dict[str, str]:
    """{'YYYY-MM': download-url} voor elk beschikbaar maandbestand."""
    out: dict[str, str] = {}
    for rec in _records(config.DS_MONTHLY):
        urls: list[str] = []
        _walk(rec, urls)
        urls = [u for u in urls if re.search(r"\.(csv|zip)(\?|$)", u, re.I) or "/files/" in u]
        if not urls:
            continue
        text = " ".join(str(v) for v in rec.values()) + " " + " ".join(urls)
        m = _MONTH_RE.search(text)
        if m:
            out[f"{m.group(1)}-{m.group(2)}"] = urls[0]
    return dict(sorted(out.items()))


def download_monthly(month: str, url: str, dest_dir: Path = config.RAW / "monthly") -> Path:
    """Download één maand; pak een zip uit naar één CSV."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    csv_path = dest_dir / f"{month}.csv"
    if csv_path.exists() and csv_path.stat().st_size > 0:
        return csv_path  # al gedownload bij een vorige (mislukte) poging
    blob = dest_dir / f"{month}.download"
    _download(url, blob)
    csv_path = dest_dir / f"{month}.csv"
    if zipfile.is_zipfile(blob):
        with zipfile.ZipFile(blob) as z:
            members = [n for n in z.namelist() if n.lower().endswith(".csv")]
            if not members:
                raise RuntimeError(f"Geen CSV in de zip van {month}: {z.namelist()}")
            with z.open(members[0]) as src, open(csv_path, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
        blob.unlink()
    else:
        blob.replace(csv_path)
    return csv_path


def official_national_monthly() -> dict[str, float]:
    """Infrabels eigen nationale stiptheid per maand ('YYYY-MM' -> %).

    Veldnamen zijn niet gedocumenteerd: we nemen het eerste veld dat op een
    maand lijkt en het eerste numerieke veld tussen 0 en 100.
    """
    out: dict[str, float] = {}
    for rec in _records(config.DS_NATIONAL):
        month, pct = None, None
        for k, v in rec.items():
            if month is None and isinstance(v, str):
                m = _MONTH_RE.search(v)
                if m:
                    month = f"{m.group(1)}-{m.group(2)}"
            elif pct is None and isinstance(v, (int, float)) and 0 < v <= 100:
                pct = float(v) * (100 if v <= 1 else 1)
        if month and pct is not None:
            out[month] = pct
    return out
