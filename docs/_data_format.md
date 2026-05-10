# Raw data format

This document is the contract for the input CSVs the engine consumes. If your
data matches this schema, the pipeline runs out of the box. If it doesn't,
either pre-transform it or extend [`config/column_mapping.py`](../config/column_mapping.py).

> Quick start: drop CSVs into `data/raw/` (default location) **or** set the
> environment variable `DRUG_SUB_RAW_DATA` to point to your existing folder.
> See [`config/paths.py::RAW_DATA_PATH`](../config/paths.py).

---

## File layout

```
<RAW_DATA_PATH>/
├── 12345.csv         ← one CSV per "market"
├── 67890.csv             (file basename = CLIENT_ID, no prefix)
├── 11111.csv
└── …                     typical dataset: 150–500 files, 50 KB – 1 GB each
```

- **One CSV = one market** (one target pharmacy, identified by `CLIENT_ID`).
- File basename **must equal** the `CLIENT_ID` value inside the file. The pipeline
  re-reads `CLIENT_ID` from a content column, not from the filename — but a
  mismatch is treated as a discovery-time error.
- Encoding: UTF-8 (with or without BOM).
- Separator: **`;`** (semicolon — pharma-industry default in the CIS).
- Decimal separator inside numeric strings: **`,`** (comma) — automatically
  parsed by Phase A1.

---

## Required columns (13)

All 13 columns must be present. Missing columns cause the file to be marked
`STATUS=INVALID` in `data/intermediate/00_preproc/markets_list.csv` and
excluded from the run. Source of truth:
[`config/column_mapping.py::RAW_REQUIRED_COLUMNS`](../config/column_mapping.py).

| # | Column                  | Type    | Description                                                                 |
|---|-------------------------|---------|-----------------------------------------------------------------------------|
| 1 | `ORG_ID`                | int64   | ID of the pharmacy that **made the sale** (renamed → `PHARM_ID`)            |
| 2 | `CLIENT_ID`             | int64   | ID of the **target pharmacy = market identifier** (constant per file)       |
| 3 | `DRUGS_ID`              | int64   | Morion drug ID (Ukrainian pharma master registry)                           |
| 4 | `PERIOD_ID`             | int64   | Date in `YYYYNNNNN` format (year + day-of-year × 1000 + intra-day counter)  |
| 5 | `Q`                     | string  | Quantity of packs sold; comma-decimal (`"3,000"`)                           |
| 6 | `V`                     | string  | Revenue in UAH; comma-decimal (`"127,50"`)                                  |
| 7 | `INN`                   | string  | International Non-proprietary Name group (renamed → `INN_NAME`)             |
| 8 | `INN_ID`                | int64   | INN group ID                                                                |
| 9 | `Full medication name`  | string  | Full SKU name with manufacturer & form (renamed → `DRUGS_NAME`)             |
|10 | `NFC Code (1)`          | string  | Broad form-of-release category (renamed → `NFC1_ID`)                        |
|11 | `NFC Code (2)`          | string  | Specific form-of-release (renamed → `NFC_ID`)                               |
|12 | `ATC Code (4)`          | string  | ATC classification, level 4 — required for validation, **not used** in computation |
|13 | `ATC Code (5)`          | string  | ATC classification, level 5 — required for validation, **not used** in computation |

> Why `ATC Code (4/5)` are required-but-unused: they were part of the original
> contract from the analyst, kept for schema-stability so a future ATC-aware
> module can be added without re-validating the dataset (`ISSUE-005` in
> [_methods_issues.md](_methods_issues.md)).

---

## Renaming applied in Phase A1

After discovery succeeds, the per-market worker renames columns to a canonical
internal schema. Source: [`config/column_mapping.py::COLUMN_RENAME_MAP`](../config/column_mapping.py).

| Raw                       | Canonical    |
|---------------------------|--------------|
| `ORG_ID`                  | `PHARM_ID`   |
| `INN`                     | `INN_NAME`   |
| `Full medication name`    | `DRUGS_NAME` |
| `NFC Code (1)`            | `NFC1_ID`    |
| `NFC Code (2)`            | `NFC_ID`     |

The other 6 useful columns (`CLIENT_ID`, `DRUGS_ID`, `PERIOD_ID`, `Q`, `V`,
`INN_ID`) keep their original names. `ATC Code (4)` and `ATC Code (5)` are
dropped at this point via `usecols=USEFUL_COLUMNS` in `pd.read_csv` (saves
~10–15 % I/O on HDD).

---

## NFC1 master registry

In addition to per-market CSVs, the engine reads
**`data/master/nfc1_config.json`** — the canonical mapping of NFC1 codes
to drug-substitution rules (which forms can substitute for which).

This file is **not in the repo** (customer-specific master data) but the
schema is fixed:

```json
{
  "NFC1_CONFIG_VERSION": "v2.1",
  "compatibility": {
    "<NFC1_CODE_A>": ["<NFC1_CODE_B>", "<NFC1_CODE_C>", …],
    …
  },
  "exclusions": {
    "<DRUGS_ID>": "reason for exclusion (free-text)"
  }
}
```

A starter `nfc1_config.json` for the Ukrainian Morion catalogue is available
on request — contact the author. For other markets you'll need to build the
NFC1 registry yourself (it's a one-time job per pharma master).

---

## Smallest possible test

To verify the pipeline picks up your data without running a full hour:

```bash
# Put 5 small CSVs into data/raw/ (or set DRUG_SUB_RAW_DATA to a folder with 5 files)
python -m pipeline.discover_markets   # should list 5 STATUS=READY rows
python -m pipeline.full_run --limit 5 # full run on first 5 markets, ~1 minute
```

Expected outputs in `results/final/`: `drug_coefficients.csv`,
`substitute_shares.csv`, `validation_report.txt` — see top-level
[README.md](../README.md) for column dictionaries.
