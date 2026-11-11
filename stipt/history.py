"""Maandcijfers voor heel het net, sinds 2014.

Die cijfers berekenen we één keer per maand en bewaren we in
history/national.json (in de repo). Zo hoeft de dagelijkse build niet
twaalf jaar aan data binnen te halen voor één grafiek.
"""

from __future__ import annotations

import json

from . import config


def load() -> dict[str, dict]:
    if config.NATIONAL_JSON.exists():
        return json.loads(config.NATIONAL_JSON.read_text())
    return {}


def update(rows: dict[str, dict]) -> dict[str, dict]:
    data = load()
    data.update(rows)
    data = dict(sorted(data.items()))
    config.NATIONAL_JSON.parent.mkdir(parents=True, exist_ok=True)
    config.NATIONAL_JSON.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    return data
