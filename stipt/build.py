"""Build: opgeslagen Parquet -> kleine JSON-bestanden voor de website.

site/data/
  meta.json               wanneer bijgewerkt, welke periode
  national.json           maandcijfers sinds 2014 + laatste 30 dagen
  ranking.json            minst stipte treinen, laatste 30 dagen
  stations/index.json     lijst van stations (voor de zoekbox)
  stations/<ptcar>.json   vertrekbord: per vertrek de kans op vertraging
  trains/<nr>.json        per trein: per halte verdeling + laatste 12 weken
"""

from __future__ import annotations

import datetime as dt
import json
import shutil
from collections import Counter
from pathlib import Path

from . import config, history, metrics, storage


def _months_back(n: int, today: dt.date) -> list[str]:
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return sorted(out)


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str))


def _quantile(sorted_vals: list[int], q: float) -> float | None:
    if not sorted_vals:
        return None
    i = (len(sorted_vals) - 1) * q
    lo, hi = int(i), min(int(i) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def build(months: int = 13, today: dt.date | None = None) -> None:
    today = today or dt.date.today()
    cache = config.PARQUET / "cache"
    paths = []
    for m in _months_back(months, today):
        paths += storage.fetch(m, cache)
    con = metrics.connect(paths)
    first, last = con.execute("SELECT min(service_date), max(service_date) FROM stops").fetchone()
    print(f"Data van {first} tot {last} ({len(paths)} bestanden)")

    if config.SITE_DATA.exists():
        shutil.rmtree(config.SITE_DATA)
    out = config.SITE_DATA

    _write(out / "meta.json", {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "first_date": first, "last_date": last,
        "definitions": {"late_s": config.LATE_S, "official_late_s": config.OFFICIAL_LATE_S},
    })

    # Heel het net
    recent = metrics.monthly_summary(con)
    hist = history.load()
    for m, v in recent.items():
        if m not in hist:  # lopende maand of nog geen definitief maandbestand
            hist[m] = {**v, "provisional": True}
    con.execute(f"CREATE TEMP VIEW runs30 AS SELECT * FROM runs WHERE service_date > DATE '{last}' - 30")
    con.execute(f"CREATE TEMP VIEW obs30 AS SELECT * FROM stop_obs WHERE service_date > DATE '{last}' - 30")
    last30 = _rows(con.execute(f"""
        SELECT
            count(*) AS runs,
            round(100 * avg((terminus_delay_s < {config.OFFICIAL_LATE_S})::INT)
                  FILTER (WHERE terminus_delay_s IS NOT NULL), 1) AS ontime_terminus_pct,
            round(100 * avg((n_not_seen > 0)::INT), 1) AS runs_not_seen_pct,
            (SELECT round(100 * avg(CASE WHEN not_seen THEN 0
                                         WHEN stop_delay_s < {config.LATE_S} THEN 1 ELSE 0 END), 1)
             FROM obs30) AS ontime_stops_pct,
            (SELECT round(avg(greatest(stop_delay_s, 0)) / 60, 1) FROM obs30) AS mean_delay_min
        FROM runs30
    """))[0]
    _write(out / "national.json", {"last_30_days": last30, "monthly": dict(sorted(hist.items()))})

    # Ranglijst
    ranking = _rows(con.execute(f"""
        SELECT
            train_no,
            mode(origin)                          AS origin,
            mode(terminus)                        AS terminus,
            mode(strftime(start_ts, '%H:%M'))     AS departs,
            mode(split_part(relation, ' ', 1))    AS type,
            count(*)                              AS runs,
            round(100 * avg((max_delay_s >= {config.LATE_S} OR n_not_seen > 0)::INT), 1) AS late_pct
        FROM runs30
        GROUP BY train_no
        HAVING count(*) >= 10
        ORDER BY late_pct DESC, runs DESC
        LIMIT 50
    """))
    _write(out / "ranking.json", ranking)

    # Vertrekborden per station (werkdagen, volledig venster)
    boards = _rows(con.execute(f"""
        WITH s AS (
            SELECT o.*, r.terminus
            FROM stop_obs o JOIN runs r USING (service_date, train_no)
            WHERE o.weekday AND o.planned_dep IS NOT NULL AND o.station IS DISTINCT FROM r.terminus
        )
        SELECT
            ptcar_no,
            any_value(station)                                   AS station,
            strftime(planned_dep, '%H:%M')                       AS time,
            train_no,
            mode(terminus)                                       AS destination,
            mode(split_part(relation, ' ', 1))                   AS type,
            count(*)                                             AS runs,
            round(100 * avg(CASE WHEN not_seen THEN 1
                                 WHEN stop_delay_s >= {config.LATE_S} THEN 1 ELSE 0 END), 1) AS late_pct,
            round(100 * avg(not_seen::INT), 1)                   AS not_seen_pct,
            round(median(greatest(stop_delay_s, 0)) / 60, 1)     AS median_min,
            round(quantile_cont(greatest(stop_delay_s, 0), 0.9) / 60, 1) AS p90_min
        FROM s
        GROUP BY ptcar_no, strftime(planned_dep, '%H:%M'), train_no
        HAVING count(*) >= {config.MIN_RUNS}
        ORDER BY ptcar_no, time
    """))
    by_station: dict[int, dict] = {}
    for b in boards:
        st = by_station.setdefault(b["ptcar_no"], {"ptcar_no": b["ptcar_no"], "station": b["station"], "departures": []})
        st["departures"].append({k: b[k] for k in ("time", "train_no", "destination", "type", "runs",
                                                    "late_pct", "not_seen_pct", "median_min", "p90_min")})
    for ptcar, st in by_station.items():
        _write(out / "stations" / f"{ptcar}.json", st)
    _write(out / "stations" / "index.json", sorted(
        ({"ptcar_no": s["ptcar_no"], "station": s["station"], "departures": len(s["departures"])}
         for s in by_station.values()),
        key=lambda s: s["station"] or "",
    ))
    print(f"{len(by_station)} vertrekborden")

    # Treinpagina's: per trein, per halte
    recent_from = last - dt.timedelta(days=config.RECENT_DAYS - 1)
    cur = con.execute("""
        SELECT
            train_no,
            ptcar_no,
            any_value(station)                                AS station,
            mode(strftime(planned_ts, '%H:%M'))               AS time,
            list(service_date ORDER BY service_date)          AS dates,
            list(CASE WHEN not_seen THEN NULL ELSE stop_delay_s END ORDER BY service_date) AS delays
        FROM stop_obs
        WHERE weekday
        GROUP BY train_no, ptcar_no
        ORDER BY train_no, time
    """)
    trains: dict[int, list[dict]] = {}
    while batch := cur.fetchmany(5000):
        for train_no, ptcar, station, time, dates, delays in batch:
            seen = sorted(d for d in delays if d is not None)
            n = len(delays)
            if n < config.MIN_RUNS:
                continue
            hist = Counter(min(max(d // 60, 0), config.HIST_MAX_MIN) for d in seen)
            trains.setdefault(train_no, []).append({
                "ptcar_no": ptcar,
                "station": station,
                "time": time,
                "runs": n,
                "late_pct": round(100 * sum(1 for d in delays if d is None or d >= config.LATE_S) / n, 1),
                "not_seen_pct": round(100 * (n - len(seen)) / n, 1),
                "median_min": round(_quantile(seen, 0.5) / 60, 1) if seen else None,
                "p90_min": round(_quantile(seen, 0.9) / 60, 1) if seen else None,
                "hist": [hist.get(i, 0) for i in range(config.HIST_MAX_MIN + 1)],
                "recent": [
                    [str(d), None if v is None else v // 60]
                    for d, v in zip(dates, delays) if d >= recent_from
                ],
            })
    for train_no, stops in trains.items():
        _write(out / "trains" / f"{train_no}.json", {"train_no": train_no, "weekdays_only": True, "stops": stops})
    print(f"{len(trains)} treinpagina's")
    con.close()
