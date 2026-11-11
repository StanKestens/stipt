"""Ingest: Infrabel -> opgekuiste Parquet -> opslag (+ maandcijfers)."""

from __future__ import annotations

import shutil

from . import config, history, metrics, sources, storage, transform


def ingest_daily() -> None:
    """Haal het dagbestand op en bewaar het als dag-asset van die maand."""
    csv = sources.download_daily()
    out = config.PARQUET / "incoming"
    for month, path, n in transform.csv_to_parquet(csv, out, kind="daily"):
        if f"month-{month}.parquet" in storage.list_assets(month):
            print(f"{month}: definitief maandbestand bestaat al, dagbestand overgeslagen")
            continue
        storage.upload(month, path)
        print(f"{path.name}: {n:,} meetpunten opgeslagen")
    csv.unlink(missing_ok=True)


def ingest_monthly(since: str | None = None, until: str | None = None, force: bool = False) -> list[str]:
    """Verwerk elk definitief maandbestand dat we nog niet hebben.

    Na een maand ruimen we de dagbestanden van die maand op en werken we
    history/national.json bij. Geeft de verwerkte maanden terug.
    """
    available = sources.list_monthly_files()
    print(f"Infrabel publiceert {len(available)} maandbestanden "
          f"({min(available, default='-')} tot {max(available, default='-')})")
    done = []
    for month, url in available.items():
        if (since and month < since) or (until and month > until):
            continue
        assets = storage.list_assets(month)
        if not force and f"month-{month}.parquet" in assets:
            continue
        print(f"{month}: downloaden…", flush=True)
        csv = sources.download_monthly(month, url)
        work = config.PARQUET / "work" / month
        written = transform.csv_to_parquet(csv, work, kind="monthly")
        csv.unlink(missing_ok=True)
        for m, path, n in written:
            if m != month:
                print(f"  let op: bestand van {month} bevat ook {n:,} rijen van {m}; overgeslagen")
                continue
            storage.upload(month, path)
            for a in assets:
                if a.startswith("day-"):
                    storage.delete(month, a)
            con = metrics.connect([path])
            summary = metrics.monthly_summary(con)
            con.close()
            history.update({k: v for k, v in summary.items() if k == month})
            print(f"  {n:,} meetpunten · {summary.get(month)}")
        shutil.rmtree(work, ignore_errors=True)
        done.append(month)
    return done
