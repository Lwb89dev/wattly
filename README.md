# WATTLY

**Understand your energy.** Wattly is a local-first desktop application that turns
your electricity bills into a historical archive with real analytics: consumption
trends, effective €/kWh, F1/F2/F3 time-band breakdowns, period comparisons and
CSV/Excel exports. No cloud, no account, no telemetry — your data stays on your machine.

![stack](https://img.shields.io/badge/stack-Flask%20·%20pywebview%20·%20SQLite%20·%20Chart.js-2563eb)

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Desktop app (native window via pywebview)
python -m wattly

# …or as a local web app (also the automatic fallback if no display/GTK)
python -m wattly --server          # → http://127.0.0.1:5055
```

Then click **Load demo data** on the dashboard (or in Settings) to explore with
14 months of realistic bills, or import your own PDF right away.

### Optional: OCR for scanned bills

Text PDFs work out of the box. For scanned/image PDFs install Tesseract —
Wattly detects it automatically and degrades gracefully when it's missing:

```bash
sudo apt install tesseract-ocr tesseract-ocr-ita   # Debian/Ubuntu
```

### Sample bills

```bash
python -m wattly --make-samples
```

Writes three PDFs to the data directory (`<data>/samples/`): two text bills in
different provider layouts (one trifaria with F1/F2/F3 bands, one monoraria)
plus an image-only copy to exercise the OCR path. All numbers are internally
consistent, so they double as parser ground truth for the test suite.

## Features

- **Import pipeline** — PDF → text extraction → OCR fallback → field extraction
  → normalization → *your review* → archive. Duplicate detection (SHA-256 +
  same-provider/same-period warnings). **Bulk mode**: one button runs the
  pipeline on every uploaded bill at once — confident bills are archived
  automatically, the rest are queued for review.
- **Bilingual UI** — full English and Italian translations (Settings →
  Language, or auto-detected from the OS; `WATTLY_LANGUAGE` overrides).
- **Extraction** — provider, POD, account, dates, billing period, total, kWh,
  fixed/energy/tax components, meter readings, tariff type, F1/F2/F3 bands;
  per-field confidence scores with cross-field validation.
- **History** — searchable/filterable archive (provider, year, month, date
  range, cost range, kWh range, free text); detail page with extraction audit
  trail; edit, re-run parsing, delete.
- **Analytics** — totals, effective price per kWh, daily averages, trends with
  rolling average, extremes, time-band stacks, year-over-year, anomaly
  detection on daily-consumption statistics.
- **Comparisons** — month/quarter/year/season/custom-range/provider, with
  day-weighted deltas (kWh, cost, €/kWh, daily avg) and % change.
- **Export** — bills/monthly/comparison to CSV; multi-sheet Excel workbook
  (Bills, Monthly, Bands, Comparison) via openpyxl.
- **UX** — light/dark/auto themes, Italian & international number/date formats,
  configurable currency, OCR toggle, editable review form that flags uncertain
  fields and records your corrections.

## Architecture

```
wattly/
├── app.py / config.py / __main__.py   # Flask factory, config, entry point
├── core/        # PURE domain logic (no Flask/SQLAlchemy — reusable on Android)
│   ├── models.py  calculators.py  analytics.py  comparisons.py
├── parsing/     # layered extraction pipeline
│   ├── pipeline.py  pdf_reader.py  ocr_engine.py  extractor.py  normalization.py
│   └── provider_parsers/            # plugin registry: base.py, generic.py, …
├── database/    # db.py (engine)  migrations.py  models.py (tables)  repositories.py
├── services/    # bill / import / analytics / export services + demo_data.py
├── web/         # routes (blueprints)  templates (Jinja)  static (CSS/JS, vendored Chart.js)
├── desktop/     # pywebview shell (the only pywebview-aware module)
├── samples.py   # sample-PDF generator (used by CLI and tests)
└── tests/       # 70+ tests: core, parsing, repositories, full web flows
```

Dependency rule: `web` → `services` → `database`/`parsing` → `core`; `core` and
`parsing` never import web or persistence anything.

### Adding a provider parser

Two parsers ship with Wattly, both validated against real bills:
`enel-energia` (both the 2024 "bolletta sintetica" (A)/(B) layout and the
2025+ itemised "Scontrino dell'energia" layout) and `octopus`. Anything
unrecognised falls back to the generic keyword/regex parser.

```python
# wattly/parsing/provider_parsers/enel.py (existing example)
from wattly.parsing.provider_parsers.base import ProviderParser

class EnelEnergiaParser(ProviderParser):
    name = "enel-energia"
    def fingerprint(self, doc): ...        # 0..1 recognition score
    def parse(self, doc): ...              # fill ExtractionOutcome

# register in provider_parsers/__init__.py
PARSERS = [EnelEnergiaParser, OctopusParser, GenericProviderParser]
```

The pipeline picks the highest fingerprint ≥ 0.5 and falls back to the generic
parser automatically. Layout-faithful synthetic samples for each shipped
parser live in `wattly/samples.py` and keep the regression tests hermetic.

## Data & privacy

Everything lives in a single SQLite database plus the original PDFs:

- default data dir: `~/.local/share/wattly` (override with `WATTLY_DATA_DIR`)
- environment: `WATTLY_DEBUG`, `WATTLY_SECRET`, `WATTLY_DB`, `WATTLY_OCR=0`

## Development

```bash
python -m pytest          # full suite (core, parsing, repositories, web E2E)
```

Money is stored as integer cents; dates as ISO strings; every derived metric is
computed only in `core/calculators.py` and recomputed on save.
