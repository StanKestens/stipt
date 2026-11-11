"""Centrale instellingen: paden, Infrabel-datasets en definities."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
RAW = DATA / "raw"            # ruwe CSV's zoals Infrabel ze levert
PARQUET = DATA / "parquet"    # opgekuiste data, één bestand per dag of maand
STORE = DATA / "store"        # lokale 'releases' wanneer je zonder GitHub draait
SITE = ROOT / "site"
SITE_DATA = SITE / "data"     # JSON die de website leest
NATIONAL_JSON = ROOT / "history" / "national.json"  # cache van maandcijfers sinds 2014

# Infrabel Open Data (Opendatasoft, API v2.1)
API = "https://opendata.infrabel.be/api/explore/v2.1/catalog/datasets"
DS_DAILY = "ruwe-gegevens-van-stiptheid-d-1"
DS_MONTHLY = "stiptheid-gegevens-maandelijksebestanden"
DS_NATIONAL = "nationale-stiptheid-per-maand"

USER_AGENT = os.environ.get(
    "STIPT_USER_AGENT", "stipt/0.1 (open-data side project; github.com/stipt)"
)

# Definities
LATE_S = 300           # wij: vanaf 5 minuten vertraging is een halte 'te laat'
OFFICIAL_LATE_S = 360  # NMBS/Infrabel: vanaf 6 minuten aan het eindstation
MIN_RUNS = 20          # minimum aantal ritten voor een cijfer op het bord
HIST_MAX_MIN = 30      # histogram 0..30 minuten, de laatste bak is '30+'
RECENT_DAYS = 84       # kalender op de treinpagina: laatste 12 weken

# Opslag: 'github' (Release-assets) of 'local' (map data/store)
STORAGE = os.environ.get(
    "STIPT_STORAGE", "github" if os.environ.get("GITHUB_ACTIONS") else "local"
)
