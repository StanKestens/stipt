"""Opslag van de Parquet-bestanden.

Op GitHub: één Release per maand (tag `data-YYYY-MM`) met als assets
- `day-YYYY-MM-DD.parquet`  zolang de maand loopt (uit het dagbestand)
- `month-YYYY-MM.parquet`   zodra Infrabel het definitieve maandbestand publiceert
Release-assets tellen niet mee in de grootte van de repo en zijn gratis.

Lokaal (STIPT_STORAGE=local): dezelfde structuur in data/store/<tag>/.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from . import config


def tag(month: str) -> str:
    return f"data-{month}"


def _gh(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *args], check=check, capture_output=True, text=True)


def list_assets(month: str) -> list[str]:
    if config.STORAGE == "local":
        d = config.STORE / tag(month)
        return sorted(p.name for p in d.glob("*.parquet")) if d.exists() else []
    r = _gh("release", "view", tag(month), "--json", "assets", check=False)
    if r.returncode != 0:
        return []
    return sorted(a["name"] for a in json.loads(r.stdout)["assets"])


def list_months() -> list[str]:
    """Alle maanden waarvoor al data is opgeslagen."""
    if config.STORAGE == "local":
        if not config.STORE.exists():
            return []
        return sorted(p.name.removeprefix("data-") for p in config.STORE.glob("data-*"))
    r = _gh("release", "list", "--limit", "1000", "--json", "tagName")
    return sorted(
        t["tagName"].removeprefix("data-")
        for t in json.loads(r.stdout)
        if t["tagName"].startswith("data-")
    )


def upload(month: str, path: Path) -> None:
    if config.STORAGE == "local":
        d = config.STORE / tag(month)
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, d / path.name)
        return
    if _gh("release", "view", tag(month), check=False).returncode != 0:
        _gh(
            "release", "create", tag(month),
            "--title", f"Data {month}",
            "--notes", f"Opgekuiste Infrabel-stiptheidsdata voor {month}.",
            "--latest=false",
        )
    _gh("release", "upload", tag(month), str(path), "--clobber")


def delete(month: str, name: str) -> None:
    if config.STORAGE == "local":
        (config.STORE / tag(month) / name).unlink(missing_ok=True)
        return
    _gh("release", "delete-asset", tag(month), name, "--yes", check=False)


def fetch(month: str, dest: Path) -> list[Path]:
    """Haal de beste data voor een maand op: het maandbestand als dat er is,
    anders alle dagbestanden. Geeft de lokale paden terug."""
    assets = list_assets(month)
    monthly = f"month-{month}.parquet"
    wanted = [monthly] if monthly in assets else [a for a in assets if a.startswith("day-")]
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for name in wanted:
        target = dest / name
        if not target.exists():
            if config.STORAGE == "local":
                shutil.copy2(config.STORE / tag(month) / name, target)
            else:
                _gh("release", "download", tag(month), "-p", name, "-D", str(dest), "--clobber")
        paths.append(target)
    return paths
