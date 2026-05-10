# Security & Data Privacy Policy

## Data Handling Statement

This repository is part of a pharmaceutical market research project that
processes pharmacy sales data. The following measures have been taken to
protect sensitive information:

### 1. Data Removal

All raw and processed data files have been **excluded from this repository**:

| Directory | Content | Status |
|:---|:---|:---|
| `data/raw/` (referenced via `config/paths.py`, not in repo) | Raw pharmacy sales CSV files | ❌ **Never published** |
| `data/intermediate/` | Per-market parquet cache (Phase A1–A4 outputs) | ❌ **Excluded** (via `.gitignore`) |
| `data/master/nfc1_config.json` | NFC1 master registry (auto-generated per dataset) | ❌ **Excluded** (regenerated locally) |
| `logs/` | Run logs with real CLIENT_IDs | ❌ **Excluded** |
| `results/final/` | Final analysis outputs (drug_coefficients, substitute_shares) | ❌ **Excluded** (folder kept via `.gitkeep`) |
| `results/_comparison/` | Snapshot of v1 results before methodology updates | ❌ **Excluded** |
| `_optional_calculations/*/inputs/`, `outputs/` | Per-task data files | ❌ **Excluded** |

### 2. Anonymization

- The customer (a real pharmacy chain) is referenced anonymously throughout
  the documentation as "pharmacy chain" or "customer" — no business name,
  brand, or geographic location is disclosed.
- Pharmacy identifiers (`CLIENT_ID`) are integer codes from the source data
  vendor; they are not exposed in any public artifact.
- Drug identifiers (`DRUGS_ID`, `INN_ID`, `NFC1_ID`) and drug names are
  reference data from a pharmaceutical catalogue. These are publicly
  available pharmaceutical metadata and do not constitute customer-sensitive
  information; they may appear in methodology documentation as illustrative
  examples.
- No patient, customer, or employee personal data was ever part of this
  dataset.

### 3. What IS Included in This Repository

Only the following are present in the repository:

- ✅ **Source code** — Python modules for the data processing pipeline.
- ✅ **Configuration files** — thresholds, parameters, column mappings.
- ✅ **Documentation** — methodology (`docs/`), per-task READMEs.
- ✅ **Methodology reports** (`reports/`) — anonymized validation, business,
  and dictionary documents that demonstrate the analytical approach without
  exposing customer-specific numbers.
- ✅ **Visualizations** — illustrative charts for documentation purposes.
- ✅ **Optional ad-hoc calculation scripts** — runnable Python utilities
  with their READMEs (data files excluded).

### 4. What is NOT Included

- ❌ Raw sales data (CSV files with transaction records).
- ❌ Processed intermediate files (per-market parquet cache).
- ❌ Final analysis numbers (drug coefficients tied to a specific dataset).
- ❌ Excel reports or output files with market-specific findings.
- ❌ Run logs with operational identifiers.
- ❌ Anything that could identify the specific customer pharmacy chain.

## Reporting Security Concerns

If you believe you have found sensitive data that was accidentally committed,
please contact the author immediately:

- **Email:** [lomanov.mail@gmail.com](mailto:lomanov.mail@gmail.com)
- **Telegram:** [@radyslav_datascience](https://t.me/radyslav_datascience)
- **WhatsApp:** [+38 (095) 035-94-05](https://wa.me/380950359405)

## Intellectual Property

All code, methodology, and documentation in this repository are proprietary.
See [LICENSE](LICENSE) for full terms.

---

**© 2026 Radyslav Lomanov. All Rights Reserved.**
