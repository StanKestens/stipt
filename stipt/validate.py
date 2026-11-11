"""Controle: liggen onze cijfers in de buurt van die van Infrabel?

We vergelijken onze 'stipt aan het eindstation (< 6 min)' met Infrabels
nationale stiptheid zonder neutralisatie. Ze zullen niet exact gelijk zijn:
Infrabel meet treinen die door de Noord-Zuidverbinding rijden aan het eerste
station van die verbinding, en wij (nog) niet. Een groot verschil wijst wel
op een fout in de pipeline of een veranderd bronformaat.
"""

from __future__ import annotations

import sys

from . import history, sources

TOLERANCE_PP = 3.0


def validate(strict: bool = False) -> int:
    ours = history.load()
    try:
        official = sources.official_national_monthly()
    except Exception as e:  # validatie mag de pipeline niet breken
        print(f"> Kon Infrabels officiële cijfers niet ophalen: {e}")
        return 0
    common = sorted(set(ours) & set(official))[-24:]
    if not common:
        print("> Nog geen overlappende maanden om te vergelijken.")
        return 0
    print("| maand | Stipt (eindstation) | Infrabel | verschil |")
    print("|---|---:|---:|---:|")
    bad = 0
    for m in common:
        a = ours[m].get("ontime_terminus_pct")
        b = official[m]
        if a is None:
            continue
        diff = a - b
        flag = " ⚠️" if abs(diff) > TOLERANCE_PP else ""
        bad += bool(flag)
        print(f"| {m} | {a:.1f}% | {b:.1f}% | {diff:+.1f} pp{flag} |")
    if bad:
        print(f"\n> {bad} maand(en) wijken meer dan {TOLERANCE_PP} procentpunt af.")
    return 1 if (strict and bad) else 0


if __name__ == "__main__":
    sys.exit(validate("--strict" in sys.argv))
