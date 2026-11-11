"""Van ruwe Infrabel-CSV naar opgekuiste Parquet.

Eén rij = één trein op één meetpunt (halte of doorrit) op één dag.

Wat we weten van de echte bestanden (maandbestand sep 2026):
- komma als scheidingsteken (de dag-export via de API gebruikt puntkomma);
  DuckDB herkent dat zelf
- datums als `01SEP2026`, tijden als `7:43:03` (uur zonder voorloopnul)
- vertraging in seconden
- extra kolommen CIRC_TYP, OP1_COD, THOP1_COD
- kolomnamen kunnen in hoofd- of kleine letters staan (API vs. bestand)

We lezen alles als tekst en casten zelf, zodat één rare waarde niet de hele
inlees stopzet.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

DATE_FORMATS = ["%d%b%Y", "%Y-%m-%d", "%d/%m/%Y", "%Y%m%d"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M"]

REQUIRED = [
    "DATDEP", "TRAIN_NO", "RELATION", "TRAIN_SERV", "PTCAR_NO", "PTCAR_LG_NM_NL",
    "LINE_NO_DEP", "LINE_NO_ARR", "RELATION_DIRECTION",
    "REAL_DATE_ARR", "REAL_TIME_ARR", "REAL_DATE_DEP", "REAL_TIME_DEP",
    "PLANNED_DATE_ARR", "PLANNED_TIME_ARR", "PLANNED_DATE_DEP", "PLANNED_TIME_DEP",
    "DELAY_ARR", "DELAY_DEP",
]


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _lit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _date(expr: str) -> str:
    parts = [f"try_strptime(trim({expr}), '{f}')" for f in DATE_FORMATS]
    return f"coalesce({', '.join(parts)})::DATE"


def _ts(d: str, t: str) -> str:
    joined = f"(trim({d}) || ' ' || trim({t}))"
    parts = [f"try_strptime({joined}, '{df} {tf}')" for df in DATE_FORMATS for tf in TIME_FORMATS]
    return f"coalesce({', '.join(parts)})"


def _sec(expr: str) -> str:
    return f"round(try_cast(replace(trim({expr}), ',', '.') AS DOUBLE))::INTEGER"


def _source(path: Path) -> str:
    return f"read_csv({_lit(str(path))}, header = true, all_varchar = true, ignore_errors = true)"


def _column_map(con: duckdb.DuckDBPyConnection, path: Path) -> dict[str, str]:
    cols = [r[0] for r in con.execute(f"DESCRIBE SELECT * FROM {_source(path)}").fetchall()]
    colmap = {c.strip().lstrip("﻿").upper(): c for c in cols}
    missing = [c for c in REQUIRED if c not in colmap]
    if missing:
        raise RuntimeError(f"{path.name}: kolommen ontbreken: {missing}. Gevonden: {cols}")
    return colmap


def select_sql(colmap: dict[str, str], path: Path) -> str:
    c = {k: _q(v) for k, v in colmap.items()}
    circ = f"nullif(trim({c['CIRC_TYP']}), '')" if "CIRC_TYP" in c else "NULL"
    return f"""
SELECT
    {_date(c['DATDEP'])}                                       AS service_date,
    try_cast(trim({c['TRAIN_NO']}) AS INTEGER)                 AS train_no,
    nullif(trim({c['RELATION']}), '')                          AS relation,
    nullif(trim({c['RELATION_DIRECTION']}), '')                AS direction,
    nullif(trim({c['TRAIN_SERV']}), '')                        AS operator,
    {circ}                                                     AS circ_typ,
    try_cast(trim({c['PTCAR_NO']}) AS INTEGER)                 AS ptcar_no,
    nullif(trim({c['PTCAR_LG_NM_NL']}), '')                    AS station,
    nullif(trim({c['LINE_NO_ARR']}), '')                       AS line_arr,
    nullif(trim({c['LINE_NO_DEP']}), '')                       AS line_dep,
    {_ts(c['PLANNED_DATE_ARR'], c['PLANNED_TIME_ARR'])}        AS planned_arr,
    {_ts(c['PLANNED_DATE_DEP'], c['PLANNED_TIME_DEP'])}        AS planned_dep,
    {_ts(c['REAL_DATE_ARR'], c['REAL_TIME_ARR'])}              AS real_arr,
    {_ts(c['REAL_DATE_DEP'], c['REAL_TIME_DEP'])}              AS real_dep,
    {_sec(c['DELAY_ARR'])}                                     AS delay_arr_s,
    {_sec(c['DELAY_DEP'])}                                     AS delay_dep_s
FROM {_source(path)}
"""


def load_csv(con: duckdb.DuckDBPyConnection, csv_path: Path) -> int:
    """Laad een ruwe CSV in de tabel `stops`. Geeft het aantal rijen terug."""
    colmap = _column_map(con, csv_path)
    con.execute(f"CREATE OR REPLACE TABLE stops AS {select_sql(colmap, csv_path)}")
    total, bad, no_plan = con.execute("""
        SELECT count(*),
               count(*) FILTER (WHERE service_date IS NULL OR train_no IS NULL),
               count(*) FILTER (WHERE planned_arr IS NULL AND planned_dep IS NULL)
        FROM stops
    """).fetchone()
    if total == 0:
        raise RuntimeError(f"{csv_path.name}: geen rijen ingelezen")

    def raw():
        return con.execute(f"SELECT * FROM {_source(csv_path)} LIMIT 2").fetchall()

    if bad / total > 0.01:
        raise RuntimeError(f"{csv_path.name}: {bad:,}/{total:,} rijen zonder datum of treinnummer. Ruw: {raw()}")
    if no_plan / total > 0.05:
        raise RuntimeError(f"{csv_path.name}: {no_plan:,}/{total:,} rijen zonder geplande tijd. Ruw: {raw()}")
    con.execute("DELETE FROM stops WHERE service_date IS NULL OR train_no IS NULL")
    return total - bad


def csv_to_parquet(csv_path: Path, out_dir: Path, kind: str) -> list[tuple[str, Path, int]]:
    """Kuis één CSV op en schrijf één Parquet per kalendermaand die erin zit.

    kind='daily'   -> `day-YYYY-MM-DD.parquet` (laatste dag in het bestand)
    kind='monthly' -> `month-YYYY-MM.parquet`
    Geeft [(maand, pad, aantal rijen)] terug.
    """
    assert kind in ("daily", "monthly")
    con = duckdb.connect()
    load_csv(con, csv_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(service_date, '%Y-%m') FROM stops ORDER BY 1"
    ).fetchall()]
    for month in months:
        last, n = con.execute(
            "SELECT max(service_date), count(*) FROM stops WHERE strftime(service_date, '%Y-%m') = $m",
            {"m": month},
        ).fetchone()
        path = out_dir / (f"day-{last}.parquet" if kind == "daily" else f"month-{month}.parquet")
        con.execute(f"""
            COPY (
                SELECT * FROM stops
                WHERE strftime(service_date, '%Y-%m') = {_lit(month)}
                ORDER BY service_date, train_no, coalesce(planned_dep, planned_arr)
            ) TO {_lit(str(path))} (FORMAT parquet, COMPRESSION zstd)
        """)
        written.append((month, path, n))
    con.close()
    return written
