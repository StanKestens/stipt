# Stipt

Hoe stipt rijden Belgische treinen écht? Niet alleen aan het eindstation, maar
in jouw station, op elke werkdag van het jaar.

Stipt haalt elke dag de ruwe stiptheidsdata van Infrabel op, kuist ze op, en
bouwt er kleine JSON-bestanden van die de website leest. Alles draait gratis op
GitHub Actions; de data zelf staat in GitHub Releases.

## Hoe het werkt

```
Infrabel Open Data
  ├─ dagbestand (D-1, elke ochtend overschreven) ──┐
  └─ maandbestanden (definitief, sinds 2014) ──────┤
                                                   ▼
                        opkuisen met DuckDB  →  Parquet (1 rij = 1 trein × 1 halte)
                                                   │
                        GitHub Release `data-YYYY-MM`
                          day-YYYY-MM-DD.parquet   zolang de maand loopt
                          month-YYYY-MM.parquet    zodra Infrabel de maand publiceert
                                                   │
                        build (laatste 13 maanden) ▼
                        site/data/*.json  →  GitHub Pages
```

| Stap | Code | Wanneer |
|---|---|---|
| Dagbestand ophalen | `python -m stipt ingest-daily` | elke dag, 2× |
| Nieuwe maandbestanden | `python -m stipt ingest-monthly` | elke dag (laatste 3 maanden) |
| Historiek sinds 2014 | `python -m stipt ingest-monthly --since 2014-01 --until 2017-12` | eenmalig, via *Historiek inladen* |
| Website-data | `python -m stipt build` | elke dag |
| Controle | `python -m stipt validate` | elke dag, in de samenvatting van de run |

Maandcijfers voor heel het net worden één keer per maand berekend en bewaard in
`history/national.json`, zodat de dagelijkse build geen twaalf jaar data nodig heeft.

## Definities

- **Te laat (Stipt):** ≥ 5 minuten vertraging bij vertrek uit een halte, of bij
  aankomst als het het eindpunt is.
- **Te laat (officieel):** ≥ 6 minuten bij aankomst aan het eindstation.
- **Niet waargenomen:** geen echte aankomst- en vertrektijd op een geplande
  halte. Meestal een (gedeeltelijk) afgeschafte rit. Voor de reiziger telt dat
  als te laat; we tonen het ook apart.
- **Vertrekborden en treinpagina's** gebruiken alleen werkdagen.

## Opzetten

1. Maak een **publieke** repo op GitHub en push deze map.
2. *Settings → Pages → Source:* **GitHub Actions**.
3. *Settings → Actions → General → Workflow permissions:* **Read and write**.
4. *Actions → Historiek inladen → Run workflow*, in blokken:
   2014-01 t/m 2017-12, 2018-01 t/m 2021-12, 2022-01 t/m vandaag.
5. *Actions → Dagelijks → Run workflow* om de eerste keer te bouwen.
   Daarna draait het vanzelf.

Let op: GitHub zet geplande workflows in een publieke repo stil na 60 dagen
zonder activiteit. De pipeline commit elke maand `history/national.json`,
dus dat zou niet mogen gebeuren.

## Lokaal draaien

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q                       # test op zelfgemaakte voorbeelddata
python -m stipt ingest-monthly --since 2026-09 --until 2026-10   # echte data
python -m stipt build --months 3
```

Zonder `GITHUB_ACTIONS` bewaart de pipeline alles in `data/store/` in plaats
van in Releases.

## Nog na te kijken bij de eerste echte run

Deze code is geschreven op basis van Infrabels documentatie, nog niet op een
echt bestand. Controleer bij de eerste run:

- het **datumformaat** in `DATDEP` en `*_DATE_*` (we proberen er vier);
- hoe de **maandbestanden-dataset** zijn downloadlinks aanbiedt
  (`sources.list_monthly_files` zoekt ze op; print het resultaat);
- hoe **afgeschafte ritten** in de data staan (lege tijden of helemaal geen rij);
- de **validatietabel**: wijken we meer dan 3 procentpunt af van Infrabel?

Bron: [Infrabel Open Data](https://opendata.infrabel.be). Stipt is niet
verbonden aan de NMBS of Infrabel.
