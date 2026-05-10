# ROADMAP — `drug_substitution_engine`

> **Версія:** 0.2
> **Створено:** 2026-04-27
> **Останнє оновлення:** 2026-04-27 (після узгодження hardware, Python env, NFC scope)
> **Власник:** Radyslav Lomanov (radyslav.lomanov@proximaresearch.com)

---

## 1. МЕТА ПРОЕКТУ

Окреме демонстраційне дослідження для презентації мережі **the pharmacy chain** на основі вже валідованих методів канонічного проекту [`cross_pharm_market_analysis`](../cross_pharm_market_analysis).

**Кінцевий результат — 4 файли:**

| # | Файл | Призначення | Колонки (обов'язкові) |
|---|------|-------------|------------------------|
| 1 | `drug_coefficients.csv` | Препарати з медіанним коефіцієнтом субституції | `DRUGS_ID; DRUG_CLASS; COEF_1; UNIQUENESS_COEF` (+ опційні) |
| 2 | `substitute_shares.csv` | Препарати-замінники з частками | `DRUGS_ID; SUBSTITUTE_DRUG_ID; SUBSTITUTE_SHARE` (+ опційні) |
| 3 | `drug_coefficients.xlsx` | XLSX-копія #1 (без кольорового маркування) | те саме |
| 4 | `substitute_shares.xlsx` | XLSX-копія #2 | те саме |

**Формат CSV:** роздільник `;`, кодування `utf-8-sig`.

**Power BI логіка:**
- Перша таблиця → загальний список препаратів з лейблом `DRUG_CLASS ∈ {UNIMODAL, MULTIMODAL}` та одним коефіцієнтом `COEF_1` (медіана після IQR)
- Друга таблиця → drill-down: при виборі SKU з першої — показ замінників з частками

---

## 2. ВХІДНІ ДАНІ

| Параметр | Значення |
|----------|----------|
| Розташування | `D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres\` |
| Формат | `{CLIENT_ID}.csv` (без префіксу `Rd2_`) |
| Кількість файлів | **207** (демонстраційні дані по м. Харків) |
| Розмір датасету | **152.35 GB** (avg 754 MB/файл, max 2.2 GB) |
| Структура колонок | Ідентична канонічному: `ORG_ID;CLIENT_ID;DRUGS_ID;PERIOD_ID;Q;V;INN;INN_ID;Full medication name;NFC Code (1);NFC Code (2);ATC Code (4);ATC Code (5)` |
| Роздільник | `;` |
| `CLIENT_ID` ідентифікація | **З вмісту файлу** (константна колонка), не з імені |

**Дані залишаються в `DATA_SETS/`** — проект читає їх напряму, без копіювання (економія дискового простору).

---

## 3. КОНФІГУРАЦІЯ ОБЧИСЛЮВАЛЬНОГО СЕРЕДОВИЩА

### 3.1. Hardware (поточний ПК)

| Параметр | Значення |
|----------|----------|
| **CPU** | Intel Core i7-9700F, 8 фізичних / 8 логічних ядер, 3.0 GHz (без Hyper-Threading) |
| **RAM** | 32 GB (31.94 GB доступно) |
| **OS** | Windows 10 Pro |
| **D:** (проект + raw + intermediate + results) | **HDD** (Seagate ST2000DM008, 2TB), вільно ~1123 GB |
| **C:** (система) | NVMe SSD (Samsung 970 EVO 500GB), вільно лише ~24 GB — **НЕ використовуємо для проекту** |

### 3.2. Storage Strategy — все на D:

| Що | Куди | Чому |
|----|------|------|
| Raw data (read-only) | `D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres\` | Дані вже там |
| Intermediate (per-market CSV) | `D:\RADYSLAV_PROJECTS\drug_substitution_engine\data\intermediate\` | ~1.2 GB, не критично щоб був SSD |
| Final results | `D:\RADYSLAV_PROJECTS\drug_substitution_engine\results\final\` | Малий обсяг |
| venv | `D:\RADYSLAV_PROJECTS\lib_env\` | ~270 MB |

**HDD-стратегія:** кожен worker читає свій файл цілком в RAM одним викликом (sequential read), процесинг — в RAM, мінімальний disk I/O. Reread файлів виключається.

### 3.3. Python Environment

| Параметр | Значення |
|----------|----------|
| Python | 3.13.1 (з `C:\Users\maksym.dmytrenko\AppData\Local\Programs\Python\Python313\python.exe`) |
| venv | `D:\RADYSLAV_PROJECTS\lib_env\` (shared для всіх RADYSLAV проектів) |
| Path до Python | `D:\RADYSLAV_PROJECTS\lib_env\Scripts\python.exe` |
| Розмір venv | ~270 MB |
| Ізоляція | ✅ Глобальні бібліотеки інших розробників не зачеплені |

### 3.4. Залежності (pinned)

```
pandas>=2.2.0, <3.0.0      # 2.3.3 — відповідає канонічному; 3.0 має breaking changes
numpy>=2.0.0, <3.0.0       # 2.4.4
scipy>=1.12.0              # 1.17.1
diptest>=0.9.0             # 0.11.0 — Hartigan's dip test для UNIMODAL/MULTIMODAL
openpyxl>=3.1.0            # 3.1.5
xlsxwriter>=3.1.0          # 3.2.9
tqdm>=4.66.0               # 4.67.3
rich>=13.0.0               # 15.0.0 — TUI
```

### 3.5. Параметри паралельності (під цей ПК)

```python
CPU_PHYSICAL_CORES   = 8
CPU_LOGICAL_CORES    = 8     # i7-9700F без HT
TOTAL_RAM_GB         = 32
AVAILABLE_RAM_GB     = 26    # 6 GB для ОС/IDE/браузера
RAM_PER_WORKER_GB    = 2.0   # вищий бюджет — файли 5-40× від канонічних
MAX_WORKERS          = 6     # 8 ядер - 1 (ОС) - 1 (main/UI) = 6
THREADS_PER_WORKER   = 1     # без HT — потоки додають context-switch overhead
MARKET_TIMEOUT_SEC   = 3600  # 60 хв per market (великі файли + HDD)
DISK_TYPE            = 'HDD'
```

---

## 4. КЛЮЧОВІ ВІДМІННОСТІ ВІД КАНОНІЧНОГО ПРОЕКТУ

### 4.1. Що **прибираємо**:
- Phase 2 Step 2.2 (Valid Data Filter / Scenario A) — приймаємо ВСІ препарати з даними, але з фільтром `MARKET_COUNT >= 20` на фінальному експорті
- Per-market бізнес-звіти XLSX (technical + business) — на демонстрацію не потрібні
- Phase 2 Step 2.1 проміжні XLSX (drug_distribution, drug_statistics для бізнесу)
- Phase 1 Step 5 cross_market XLSX, тільки CSV для агрегації
- Кольорове маркування в фінальних XLSX
- Окремі довідники: `inn_list.csv`, `nfc1_list.csv`, `nfc2_list.csv` (несемо в потоці даних)
- NFC2_ID обробка (не використовується ніким з логіки)
- **NFC декомпозиція в DiD** (`LIFT_SAME_NFC1`, `LIFT_DIFF_NFC1`, `SHARE_SAME_NFC1`, `SHARE_DIFF_NFC1`) — не потрібна для наших фінальних 2 файлів

### 4.2. Що **додаємо**:
- **Класифікація унімодальні / мультимодальні** через Hartigan's dip test (`diptest`)
- **Колонка `UNIQUENESS_COEF = 1 − COEF_1`** в `drug_coefficients.csv`
- **TUI прогрес-бар** з ETA через `rich` бібліотеку
- **`.bat` launcher** для подвійного кліка
- **Швидкий sniff** при discovery (читання `nrows=3` для CLIENT_ID/валідації)
- **Колонка `STATUS`** в `markets_statistics.csv` (`READY` / `EMPTY` / `MALFORMED`)

### 4.3. Що **залишається** (методологічна основа):
- DiD методологія Phase 1 повністю
- Stock-out detection з 3-рівневою валідацією (INN-level + drug-level × 2)
- **NFC Compatibility Filter** (`nfc_compatibility.py`) — критично для коректної ідентифікації substitutes (ORAL_GROUP взаємозамінні)
- **`SAME_NFC1` bool флаг** як опційна колонка в `substitute_shares.csv` (корисно для Power BI drill-down)
- Phantom Substitutes Filter
- Zero-LIFT Filter
- IQR outlier detection per drug
- LIFT-зважена агрегація substitutes (з дедублікацією INTERNAL_LIFT по `(CLIENT_ID, STOCKOUT_DRUG_ID)`)
- Інваріант: `SUM(SUBSTITUTE_SHARE per stockout drug) = 1.0`
- 3-рівнева паралелізація (ProcessPool); ThreadPool НЕ використовуємо (CPU без HT)
- **Фільтр `MARKET_COUNT >= 20`** на фінальному експорті (Sequential Analyzer Study 02 critère)

---

## 5. АРХІТЕКТУРА ПРОЕКТУ

```
drug_substitution_engine/
│
├── ROADMAP.md                          ← цей файл (план + рішення)
├── LOGS.md                             ← хронологія робіт
├── ALGORITHMS.md                       ← методологія + формули
├── README.md                           ← короткий quick-start (TBD)
├── requirements.txt                    ← залежності
├── run.bat                             ← Windows launcher (TBD)
│
├── config/
│   ├── __init__.py
│   ├── paths.py                        ← шляхи (DATA_SETS, intermediate, results)
│   ├── machine_params.py               ← параметри ПК + workers
│   ├── column_mapping.py               ← маппінг колонок (копія канонічного)
│   ├── stockout_params.py              ← пороги stock-out detection (копія)
│   └── thresholds.py                   ← MIN_MARKET_COUNT та інше
│
├── core/                               ← бізнес-логіка
│   ├── __init__.py
│   ├── etl.py                          ← gap fill, parse_period_id, weekly aggregation
│   ├── stockout.py                     ← stockout detection + 3-level validation
│   ├── did.py                          ← DiD: market_growth, lift, shares
│   ├── nfc.py                          ← NFC compatibility (копія канонічного)
│   ├── substitution.py                 ← substitute analysis + LIFT-weighted agg
│   └── modality.py                     ← Hartigan dip test для UNIMODAL/MULTIMODAL
│
├── pipeline/
│   ├── __init__.py
│   ├── runner.py                       ← головний оркестратор + ProcessPool
│   ├── discover_markets.py             ← preprocessing: знайти всі ринки
│   ├── per_market.py                   ← Phase A: один ринок (всі кроки)
│   ├── cross_market.py                 ← Phase B: агрегація медіан + modality
│   └── final_export.py                 ← Phase C: 2 CSV + 2 XLSX
│
├── ui/
│   ├── __init__.py
│   ├── progress.py                     ← rich TUI (progress, ETA, status)
│   └── logger.py                       ← структурований лог у файл
│
├── data/
│   └── intermediate/                   ← per-market проміжні CSV
│       ├── 00_preproc/                 ← markets_list, markets_statistics, drugs_list
│       └── 01_per_market/{CLIENT_ID}/  ← sub_coef.csv, sub_drugs.csv per ринок
│
├── results/
│   └── final/                          ← 2 CSV + 2 XLSX для Power BI + validation_report.txt
│
├── logs/                               ← run logs (timestamp у назві)
│
└── docs/                               ← розширена документація (опційно)
    ├── 00_PROJECT_OVERVIEW.md
    ├── 01_METHODOLOGY.md
    ├── 02_OUTPUT_SPECIFICATION.md
    ├── 03_HARDWARE_CONFIG.md
    └── 04_USAGE.md
```

**Notes:**
- `data/intermediate/00_preproc/` зберігає тільки 3 CSV (не 6 як у канонічному): `markets_list.csv`, `markets_statistics.csv`, `drugs_list.csv`
- INN_NAME, NFC1_ID несемо в потоці даних, не в окремих довідниках

---

## 6. PIPELINE (ПОЕТАПНО)

> Детальні алгоритми та формули — у [ALGORITHMS.md](./ALGORITHMS.md)

### Phase A — Per-Market Processing (паралельно × ринки)

| Крок | Що робить | Output |
|------|-----------|--------|
| A0 | Discovery: scan `pd_ds_4_pres/*.csv`, sniff CLIENT_ID, валідація колонок | `markets_list.csv`, `markets_statistics.csv`, `drugs_list.csv` |
| A1 | Завантаження CSV, парсинг PERIOD_ID, gap filling по тижнях, market totals | (in-memory DataFrame) |
| A2 | Stock-out detection (3-рівнева валідація) | `events` (in-memory) |
| A3 | DiD core: market growth, expected, LIFT, shares | `did_results` |
| A4 | Substitute analysis: TOTAL_LIFT per (stockout, substitute), zero-LIFT filter | `substitutes` |
| A5 | Збереження двох плоских CSV: | `intermediate/01_per_market/{CLIENT_ID}/sub_coef.csv`<br>`intermediate/01_per_market/{CLIENT_ID}/sub_drugs.csv` |

**Оптимізація:** A1–A5 у одному worker без записів між кроками.

### Phase B — Cross-Market Aggregation (sequential)

| Крок | Що робить | Output |
|------|-----------|--------|
| B1 | Збір усіх `sub_coef.csv` → wide-format (DRUGS × MARKETS) | (in-memory) |
| B2 | IQR-фільтрація outliers per DRUGS_ID | (in-memory) |
| B3 | Hartigan's dip test → класифікація `UNIMODAL` / `MULTIMODAL` per drug | (in-memory) |
| B4 | Розрахунок `MEDIAN_SHARE_INTERNAL` per drug (після IQR) | (in-memory) |

### Phase C — Final Export (sequential)

| Крок | Що робить | Output |
|------|-----------|--------|
| C0 | Фільтр `MARKET_COUNT >= 20` (відсіює препарати з малою вибіркою) | accepted set |
| C1 | Формування `drug_coefficients.csv` | `results/final/drug_coefficients.csv` |
| C2 | LIFT-зважена агрегація substitutes cross-market (з дедублікацією INTERNAL_LIFT) | `results/final/substitute_shares.csv` |
| C3 | XLSX-копії обох файлів без кольорового маркування | `results/final/*.xlsx` |
| C4 | Валідація інваріантів | `results/final/validation_report.txt` |

---

## 7. ФОРМАТ ВИХІДНИХ ФАЙЛІВ

### 7.1. `drug_coefficients.csv` / `.xlsx`

**Обов'язкові колонки:**

| Колонка | Тип | Опис |
|---------|-----|------|
| `DRUGS_ID` | int | Morion ID препарату |
| `DRUG_CLASS` | str | `UNIMODAL` / `MULTIMODAL` (за dip test) |
| `COEF_1` | float ∈ [0,1] | Медіанний коефіцієнт субституції (після IQR) |
| `UNIQUENESS_COEF` | float ∈ [0,1] | `1 − COEF_1` |

**Опційні колонки** (фінально визначаються на Phase C):

| Колонка | Чому корисно для Power BI |
|---------|---------------------------|
| `DRUGS_NAME` | Людська назва для відображення |
| `INN_ID` / `INN_NAME` | Групування Power BI по діючій речовині |
| `NFC1_ID` | Фільтр за формою випуску |
| `MARKET_COUNT` | Скільки ринків покрито (надійність) |

**Сортування:** `COEF_1` DESC.

### 7.2. `substitute_shares.csv` / `.xlsx`

**Обов'язкові колонки:**

| Колонка | Тип | Опис |
|---------|-----|------|
| `DRUGS_ID` | int | ID stockout препарату |
| `SUBSTITUTE_DRUG_ID` | int | ID препарату-замінника |
| `SUBSTITUTE_SHARE` | float ∈ [0,1] | LIFT-зважена частка |

**Опційні колонки:**

| Колонка | Чому корисно |
|---------|--------------|
| `DRUGS_NAME` | Stockout препарат |
| `SUBSTITUTE_DRUG_NAME` | Замінник |
| `SAME_NFC1` | bool: чи замінник тієї ж форми (для Power BI filter) |
| `SUBSTITUTE_RANK` | Ранг (1 = найбільша частка) |
| `MARKETS_COUNT` | На скількох ринках спостерігалась пара |

**Інваріант:** `SUM(SUBSTITUTE_SHARE per DRUGS_ID) = 1.0` (toleration ±0.01)

---

## 8. ФОРМАТ ЗАПУСКУ (`.bat` + Python TUI)

### `run.bat`

```bat
@echo off
cd /d "%~dp0"
"D:\RADYSLAV_PROJECTS\lib_env\Scripts\python.exe" -m pipeline.runner
pause
```

### Python TUI (rich)

При запуску показує:

```
┌─ Drug Substitution Engine ─────────────────────────────────┐
│ Started: 2026-04-27 14:30:21                                     │
│ Workers: 6 (CPU: 8 cores, RAM: 32 GB, Disk: HDD)                 │
└──────────────────────────────────────────────────────────────────┘

Phase A: Per-Market Processing
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 145/207  ETA 00:14:32
  Active: [103097, 1289543, 4448454, ...]
  Done: 145  Failed: 0  No data: 2

Phase B: Cross-Market Aggregation     ⏳ Pending
Phase C: Final Export                 ⏳ Pending
```

---

## 9. ПОЕТАПНИЙ ПЛАН РЕАЛІЗАЦІЇ (з контрольними точками)

> Кожен крок завершується **узгодженням з користувачем** перед переходом до наступного.

| # | Крок | Що створено | Контрольна точка | Статус |
|---|------|-------------|-------------------|--------|
| **0** | Узгодження ROADMAP | `ROADMAP.md` (v0.1) | Підтверджено | ✅ |
| **0a** | Hardware analysis | (аналіз ПК) | i7-9700F, 32 GB, HDD на D: | ✅ |
| **0b** | Storage strategy | (рішення) | Все на D: | ✅ |
| **0c** | Python env | `lib_env/` + 8 пакетів | venv, pandas 2.3.3 | ✅ |
| **0d** | NFC scope | (рішення) | Залишити фільтр + SAME_NFC1, прибрати декомпозицію | ✅ |
| **0e** | ROADMAP v0.2 + LOGS + ALGORITHMS | 3 .md файли | Створено | ✅ |
| **1** | Skeleton + Preprocessing | `config/`, `pipeline/discover_markets.py` | Тест на 5 файлах | ✅ |
| **2** | Core ETL (Phase A1) | `core/etl.py` + smoke-test | Парсинг + gap filling 1 ринку | ✅ |
| **3** | Stock-out detection (Phase A2) | `core/stockout.py` | 3-рівнева валідація | ✅ |
| **4** | DiD analysis (Phase A3) | `core/did.py`, `core/nfc.py` (+ ISSUE-013 fix) | LIFT, SHARE для 1 ринку | ✅ |
| **5** | Substitute analysis (Phase A4) | інтегровано в `pipeline/per_market.py` (Q-A3.3 reuse) | sub_coef per ринок | ✅ |
| **6** | Per-market pipeline (Phase A) | `pipeline/per_market.py` | 1 ринок повністю A1→A4 | ✅ |
| **7** | Паралельний runner | `pipeline/runner.py` | 5 ринків паралельно | ✅ |
| **8** | Cross-market + modality (Phase B) | `pipeline/cross_market.py` (Hartigan dip test inline) | UNIMODAL/MULTIMODAL для тестової вибірки | ✅ |
| **9** | Final export (Phase C) | `pipeline/final_export.py` | 2 CSV + 2 XLSX, інваріант SUM=1.0 | ✅ |
| **10** | TUI (Rich Live) + persistent logging + corruption-aware resume | `pipeline/runner.py` (інтегрований TUI), `pipeline/full_run.py`, `core/io_utils.py`, `run.bat` | Progress + ETA + auto-recovery | ✅ |
| **11** | Smoke-test 3 ринки | (smoke-test) | 12/12 invariants PASSED, 10s | ✅ |
| **12** | Повний запуск 205 ринків | Фінальні артефакти | 9h 35m, 0 errors, 12/12 invariants | ✅ |
| **13** | Бізнес-звіт по результатах | `results/final/business_report.txt` | 9 секцій, 3 приклади препаратів | ✅ |
| **14** | UI cosmetic fixes у runner | `pipeline/runner.py` (active workers + ETA fix) | Жива перевірка на 2 ринках | ✅ |
| **15** | Реструктуризація проекту і ребрендинг | `D:\RADYSLAV_PROJECTS\PROJECTS\drug_substitution_engine\` + `_lib_env\` | Smoke-test: 47.9s, 12/12 invariants PASSED | ✅ |
| **16** | (опційно) GitHub portfolio | (наступний етап) | Sanitization + README + .gitignore + LICENSE | 🔄 |
| **17** | (опційно) PyInstaller .exe | `dist/drug_substitution_engine.exe` | Standalone бінарник | ⏳ |

**Архітектурні відхилення від початкового плану:**
- `core/substitution.py` → інтегровано в `pipeline/per_market.py` (Q-A3.3 optimization: substitute_pairs з Phase A3 використовуються прямо в Phase A4 без перерахунку LIFT)
- `core/modality.py` → інтегровано в `pipeline/cross_market.py` (Hartigan dip test через diptest бібліотеку inline)
- `ui/progress.py`, `ui/logger.py` → не виокремлено в `ui/` пакет; Rich Live dashboard імплементовано прямо в `pipeline/runner.py`, persistent file-logging — у `pipeline/full_run.py`
- `core/io_utils.py` → доданий (поза початковим планом) для corruption-aware resume через `pq.read_metadata()`
- `config/thresholds.py` → не виокремлено; MIN_MARKET_COUNT передається через CLI-параметр `--min-market-count`

---

## 10. РИЗИКИ ТА МІТИГАЦІЯ

| Ризик | Імовірність | Мітигація |
|-------|-------------|-----------|
| **OOM** при 152 GB raw + 6 workers | Середня | Кожен worker читає 1 файл (~800 MB max) у RAM; 6 × 2 GB = 12 GB; 32 GB RAM → запас |
| **Час обробки > 4 годин** | Середня (HDD) | Sequential read per worker, мінімум I/O після |
| **Pandas PerformanceWarning** широка матриця 207 ринків | Низька (вже фіксили в canonical) | Pivot tables замість iterrows |
| **Помилка на 1 файлі ламає pipeline** | Низька | try/except per-market + STATUS=MALFORMED |
| **Замало дискового простору** | Низька (1.1 TB free) | Pre-flight check `shutil.disk_usage()` |
| **Структура нових файлів відрізняється** | Низька (перевірив 3) | Валідація колонок при першому читанні + fail-fast |
| **pandas 3.x breaking changes** | Виключено | Pinned `pandas<3.0.0` |

---

## 11. КРИТЕРІЇ ГОТОВНОСТІ

- [x] 4 файли (2 CSV + 2 XLSX) у `results/final/` — drug_coefficients + substitute_shares (6 265 препаратів, 182 164 пар)
- [x] `validation_report.txt` з усіма перевіреними інваріантами — 12/12 PASSED
- [x] `run.bat` запускає повний цикл подвійним кліком
- [x] TUI показує прогрес з ETA — Rich Live з кастомним banner-ETA
- [x] Час повного запуску на 207 ринках задокументовано — 9h 35m 42s на 205 ринках (2 файли OVERSIZED, виключені)
- [x] Перевірка на новому ПК — налаштування лише через `config/machine_params.py`
- [x] (бонус) Бізнес-звіт `business_report.txt` для аналітика+замовника

---

## 12. ВЕДЕННЯ ДОКУМЕНТАЦІЇ

4 живих документи в корені проекту:

| Файл | Призначення | Коли оновлювати |
|------|-------------|-----------------|
| **ROADMAP.md** (цей) | План + ухвалені рішення | При зміні архітектури/scope |
| **LOGS.md** | Хронологія виконаних робіт | Після кожного завершеного кроку |
| **ALGORITHMS.md** | Методологія + формули | При реалізації нового алгоритму |
| **_methods_issues.md** | Tech debt: слабкі місця методології | При виявленні нової слабкості / прийнятого свідомо спрощення |

Опційно: розширена документація в `docs/` (у фінальній фазі для замовника).

---

## СТАТУС: ✅ ЗАВЕРШЕНО — наступний етап: підготовка до GitHub-портфоліо (Крок 15)

**Підсумок проекту:**
- 205 ринків × 152 GB сирих CSV → 6 265 препаратів × 182 164 пар замінників
- Pipeline: 9 годин 35 хвилин (5.97× speedup на 6 workers)
- 0 помилок, 12/12 валідаційних інваріантів пройдено
- 4 файли для Power BI + 1 бізнес-звіт + 1 validation report

**Що далі:**
- Крок 15 — підготовка коду до публікації на GitHub як портфоліо: `.gitignore`, `requirements.txt`, `LICENSE`, sanitize hardcoded paths/IDs, переписати README як showcase
