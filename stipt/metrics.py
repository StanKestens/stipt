"""Gedeelde definities bovenop de opgekuiste data.

Termen:
- meetpunt / halte: één rij in `stops`
- rit (run): één trein (train_no) op één dag (service_date)
- haltevertraging: vertrekvertraging, of aankomstvertraging aan het eindpunt
- niet waargenomen: geen echte aankomst- én geen vertrektijd. Dat wijst meestal
  op een (gedeeltelijk) afgeschafte rit. We tellen het apart én, voor de
  reiziger, als 'te laat'.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from . import config


def connect(paths: list[Path]) -> duckdb.DuckDBPyConnection:
    if not paths:
        raise RuntimeError("Geen Parquet-bestanden om te verwerken")
    con = duckdb.connect()
    files = ", ".join("'" + str(p).replace("'", "''") + "'" for p in paths)
    con.execute(f"CREATE VIEW stops AS SELECT * FROM read_parquet([{files}], union_by_name = true)")
    con.execute(f"""
        CREATE TABLE stop_obs AS
        SELECT
            *,
            coalesce(planned_dep, planned_arr)                         AS planned_ts,
            CASE WHEN planned_dep IS NULL THEN delay_arr_s
                 ELSE delay_dep_s END                                  AS stop_delay_s,
            (real_arr IS NULL AND real_dep IS NULL)                    AS not_seen,
            isodow(service_date) <= 5                                  AS weekday
        FROM stops
    """)
    con.execute(f"""
        CREATE TABLE runs AS
        SELECT
            service_date,
            train_no,
            any_value(relation)                              AS relation,
            arg_min(station, planned_ts)                     AS origin,
            arg_max(station, planned_ts)                     AS terminus,
            arg_max(delay_arr_s, planned_ts)                 AS terminus_delay_s,
            max(stop_delay_s)                                AS max_delay_s,
            count(*)                                         AS n_points,
            count(*) FILTER (WHERE not_seen)                 AS n_not_seen,
            min(planned_ts)                                  AS start_ts
        FROM stop_obs
        GROUP BY service_date, train_no
    """)
    return con


MONTHLY_SUMMARY_SQL = f"""
WITH r AS (
    SELECT strftime(service_date, '%Y-%m') AS month, * FROM runs
), s AS (
    SELECT strftime(service_date, '%Y-%m') AS month, * FROM stop_obs
)
SELECT
    month,
    count(*)                                                                    AS runs,
    round(100 * avg((terminus_delay_s < {config.OFFICIAL_LATE_S})::INT)
          FILTER (WHERE terminus_delay_s IS NOT NULL), 2)                        AS ontime_terminus_pct,
    round(100 * avg((max_delay_s < {config.LATE_S} AND n_not_seen = 0)::INT), 2) AS ontime_whole_run_pct,
    round(100 * avg((n_not_seen > 0)::INT), 2)                                  AS runs_not_seen_pct,
    any_value(sx.ontime_stops_pct)                                              AS ontime_stops_pct,
    any_value(sx.mean_delay_min)                                                AS mean_delay_min,
    any_value(sx.points)                                                        AS points
FROM r
JOIN (
    SELECT
        month,
        count(*)                                                                 AS points,
        round(100 * avg(CASE WHEN not_seen THEN 0
                             WHEN stop_delay_s < {config.LATE_S} THEN 1 ELSE 0 END), 2) AS ontime_stops_pct,
        round(avg(greatest(stop_delay_s, 0)) / 60, 2)                            AS mean_delay_min
    FROM s
    GROUP BY month
) sx USING (month)
GROUP BY month
ORDER BY month
"""


def monthly_summary(con: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    cur = con.execute(MONTHLY_SUMMARY_SQL)
    cols = [d[0] for d in cur.description]
    return {row[0]: dict(zip(cols[1:], row[1:])) for row in cur.fetchall()}
