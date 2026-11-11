"""Command line: python -m stipt <commando>

  ingest-daily                       dagbestand ophalen en opslaan
  ingest-monthly [--since YYYY-MM]   definitieve maandbestanden verwerken
                 [--until YYYY-MM] [--force]
  build [--months 13]                JSON voor de website bouwen
  validate [--strict]                vergelijken met Infrabels eigen cijfers
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="stipt")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ingest-daily")
    m = sub.add_parser("ingest-monthly")
    m.add_argument("--since")
    m.add_argument("--until")
    m.add_argument("--force", action="store_true")
    b = sub.add_parser("build")
    b.add_argument("--months", type=int, default=13)
    v = sub.add_parser("validate")
    v.add_argument("--strict", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "ingest-daily":
        from .ingest import ingest_daily
        ingest_daily()
    elif a.cmd == "ingest-monthly":
        from .ingest import ingest_monthly
        done = ingest_monthly(a.since, a.until, a.force)
        print(f"Verwerkt: {', '.join(done) or 'niets nieuws'}")
    elif a.cmd == "build":
        from .build import build
        build(a.months)
    elif a.cmd == "validate":
        from .validate import validate
        return validate(a.strict)
    return 0


if __name__ == "__main__":
    sys.exit(main())
