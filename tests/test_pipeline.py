"""Test de hele keten op een kleine, zelfgemaakte Infrabel-CSV.

Drie treinen, alle 22 werkdagen van oktober 2026:
- 100: Leuven -> Herent -> Brussel-Noord, altijd op tijd
- 200: onderweg 7 min te laat, aan het eindstation nog 4 min ('officieel stipt')
- 300: op dag 0 niet waargenomen in Herent (afgeschafte halte)
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

COLS = ["DATDEP", "TRAIN_NO", "RELATION", "TRAIN_SERV", "PTCAR_NO", "LINE_NO_DEP",
        "REAL_TIME_ARR", "REAL_TIME_DEP", "PLANNED_TIME_ARR", "PLANNED_TIME_DEP",
        "DELAY_ARR", "DELAY_DEP", "RELATION_DIRECTION", "PTCAR_LG_NM_NL", "LINE_NO_ARR",
        "PLANNED_DATE_ARR", "PLANNED_DATE_DEP", "REAL_DATE_ARR", "REAL_DATE_DEP"]

STATIONS = [(1, "LEUVEN"), (2, "HERENT"), (3, "BRUSSEL-NOORD")]


def _t(base: dt.datetime, minutes: float) -> str:
    s = (base + dt.timedelta(minutes=minutes)).strftime("%H:%M:%S")
    return s[1:] if s.startswith("0") else s  # zoals Infrabel: 7:43:03


def _rows(day: dt.date, train: int, start: str, delays: list[int | None], fmt: str) -> list[list[str]]:
    base = dt.datetime.combine(day, dt.time.fromisoformat(start))
    d = day.strftime(fmt).upper()
    out = []
    for i, ((no, name), delay) in enumerate(zip(STATIONS, delays)):
        first, lastst = i == 0, i == len(STATIONS) - 1
        plan = i * 10
        seen = delay is not None
        dl = delay or 0
        out.append([
            d, str(train), f"IC {train // 100:02d}", "SNCB/NMBS", str(no), "36",
            "" if first or not seen else _t(base, plan + dl / 60),
            "" if lastst or not seen else _t(base, plan + dl / 60),
            "" if first else _t(base, plan),
            "" if lastst else _t(base, plan),
            "" if first or not seen else str(dl),
            "" if lastst or not seen else str(dl),
            "IC: LEUVEN -> BRUSSEL-NOORD", name, "36",
            "" if first else d, "" if lastst else d,
            "" if first or not seen else d, "" if lastst or not seen else d,
        ])
    return out


def _write_csv(path, days, fmt="%d%b%Y", sep=","):
    lines = [sep.join(COLS)]
    for k, day in enumerate(days):
        rows = _rows(day, 100, "08:00:00", [0, 30, 60], fmt)
        rows += _rows(day, 200, "08:07:00", [180, 420, 240], fmt)
        rows += _rows(day, 300, "08:14:00", [0, None if k == 0 else 60, 120], fmt)
        lines += [sep.join(r) for r in rows]
    path.write_text("\n".join(lines) + "\n")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    from stipt import config
    monkeypatch.setattr(config, "STORAGE", "local")
    monkeypatch.setattr(config, "PARQUET", tmp_path / "parquet")
    monkeypatch.setattr(config, "STORE", tmp_path / "store")
    monkeypatch.setattr(config, "SITE_DATA", tmp_path / "site" / "data")
    monkeypatch.setattr(config, "NATIONAL_JSON", tmp_path / "history" / "national.json")
    return tmp_path


def _weekdays(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        if d.isoweekday() <= 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


@pytest.mark.parametrize("fmt,sep", [("%d%b%Y", ","), ("%Y-%m-%d", ";"), ("%d/%m/%Y", ";")])
def test_transform_parses_date_formats(env, fmt, sep):
    from stipt import transform
    csv = env / "in.csv"
    _write_csv(csv, [dt.date(2026, 10, 5)], fmt, sep)
    [(month, path, n)] = transform.csv_to_parquet(csv, env / "out", kind="daily")
    assert month == "2026-10"
    assert path.name == "day-2026-10-05.parquet"
    assert n == 9


def test_end_to_end(env):
    from stipt import metrics, storage, transform
    from stipt.build import build

    days = _weekdays(dt.date(2026, 10, 1), 22)
    csv = env / "month.csv"
    _write_csv(csv, days)
    for month, path, _ in transform.csv_to_parquet(csv, env / "out", kind="monthly"):
        storage.upload(month, path)

    con = metrics.connect(storage.fetch("2026-10", env / "cache"))
    s = metrics.monthly_summary(con)["2026-10"]
    # trein 200 is altijd 'officieel stipt' (4 min aan het eindstation)
    assert s["ontime_terminus_pct"] == 100.0
    # maar nooit stipt over de hele rit
    assert s["ontime_whole_run_pct"] < 67
    assert s["runs"] == 66

    build(months=2, today=days[-1])
    out = env / "site" / "data"
    leuven = json.loads((out / "stations" / "1.json").read_text())
    by_train = {d["train_no"]: d for d in leuven["departures"]}
    assert by_train[100]["late_pct"] == 0.0
    assert by_train[100]["destination"] == "BRUSSEL-NOORD"
    herent = {d["train_no"]: d for d in json.loads((out / "stations" / "2.json").read_text())["departures"]}
    assert herent[200]["late_pct"] == 100.0       # 7 min in Herent
    assert herent[300]["not_seen_pct"] == 4.5     # 1 van 22 dagen
    train = json.loads((out / "trains" / "200.json").read_text())
    assert [s["station"] for s in train["stops"]] == ["LEUVEN", "HERENT", "BRUSSEL-NOORD"]
    assert sum(train["stops"][1]["hist"]) == 22
    ranking = json.loads((out / "ranking.json").read_text())
    assert ranking[0]["train_no"] == 200
