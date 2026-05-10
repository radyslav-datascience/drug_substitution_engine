# ALGORITHMS — `drug_substitution_engine`

> **Версія:** 1.0 (skeleton)
> **Призначення:** Технічний опис методології та алгоритмів кожного етапу pipeline. Заповнюється покроково в міру реалізації.
> **Аудиторія:** розробник (Claude+користувач), аналітик Power BI, AI-агенти при відновленні контексту.

---

## ПРИНЦИП ВЕДЕННЯ

- Кожен етап pipeline отримує власний розділ (наприклад: `## Phase A1: Data Aggregation`)
- Розділ заповнюється **під час або одразу після** реалізації кроку
- Для не-реалізованих етапів — статус `⏳ TBD` та посилання на канонічний документ

### Шаблон розділу

```markdown
## Phase X.Y: Назва кроку

**Статус:** ⏳ TBD / 🔄 In Progress / ✅ Implemented
**Реалізація:** `path/to/script.py`
**Відповідає канонічному:** `cross_pharm_market_analysis/.../canonical_script.py`
**Версія алгоритму:** vN.M (короткий опис змін vs канонічний)

### Призначення
(2-3 речення про ціль кроку)

### Вхід / Вихід
- Вхід: (файли/структури)
- Вихід: (файли/структури)

### Алгоритм
1. ...
2. ...
(псевдокод або послідовність операцій)

### Ключові формули
| Формула | Опис |
|---------|------|
| ... | ... |

### Edge Cases
| Ситуація | Поведінка |
|----------|-----------|
| ... | ... |

### Інваріанти
- (умови що завжди мають виконуватися)

### Відмінності від канонічного
- (якщо є модифікації)
```

---

## ВЕРХНЬОРІВНЕВА АРХІТЕКТУРА

```
┌──────────────────────────────────────────────────────────────────────┐
│                  Vhid: 207 CSV files (152 GB)                        │
│         D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres\*.csv            │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE A — Per-Market Processing (паралельно × ринки, 6 workers)      │
│                                                                       │
│  A0 Discovery → A1 ETL → A2 Stockout → A3 DiD → A4 Substitutes       │
│      → A5 Save intermediate                                           │
│                                                                       │
│  Output: data/intermediate/01_per_market/{CLIENT_ID}/                │
│            ├── sub_coef.csv     (per-market coefficients)            │
│            └── sub_drugs.csv    (substitute pairs)                    │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE B — Cross-Market Aggregation (sequential)                      │
│                                                                       │
│  B1 Wide-format matrix → B2 IQR outlier filter → B3 Dip test         │
│      → B4 Median calculation                                          │
│                                                                       │
│  Output: in-memory DataFrame (drug_aggregates)                        │
└──────────────────────────────┬───────────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────────┐
│  PHASE C — Final Export (sequential)                                  │
│                                                                       │
│  C0 MARKET_COUNT≥20 filter → C1 drug_coefficients.csv                │
│      → C2 substitute_shares.csv (LIFT-weighted)                       │
│      → C3 XLSX copies → C4 validation                                 │
│                                                                       │
│  Output: results/final/                                               │
│            ├── drug_coefficients.csv / .xlsx                          │
│            ├── substitute_shares.csv / .xlsx                          │
│            └── validation_report.txt                                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## ГЛОСАРІЙ КЛЮЧОВИХ ТЕРМІНІВ

| Термін | Визначення |
|--------|------------|
| **DiD** | Difference-in-Differences — економетричний метод оцінки ефекту stockout |
| **Stock-out** | Період, коли препарат відсутній у цільовій аптеці (Q=0 ≥ 1 тиждень) |
| **CLIENT_ID** | ID цільової аптеки (= market identifier; константа всередині 1 файлу) |
| **ORG_ID** | ID аптеки-продавця (target якщо `==CLIENT_ID`, інакше — конкурент) |
| **PRE-period** | Тижні до stock-out (baseline для DiD) |
| **DURING-period** | Тижні самого stock-out |
| **POST-period** | Тижні після відновлення продажів |
| **LIFT** | Додаткові продажі substitutes через stockout: `max(0, ACTUAL - EXPECTED)` |
| **EXPECTED** | Counterfactual продажі: `PRE_AVG × MARKET_GROWTH` |
| **MARKET_GROWTH** | `MARKET_DURING / MARKET_PRE` (тренд ринку, агрегований по INN) |
| **INTERNAL_LIFT** | Сума LIFT всіх substitutes одного stockout drug на одному ринку |
| **LOST_SALES** | LIFT конкурентів (попит, що пішов з аптеки) |
| **SHARE_INTERNAL** | `INTERNAL_LIFT / (INTERNAL_LIFT + LOST_SALES)` per-market коефіцієнт |
| **SUBSTITUTE_SHARE** | Частка LIFT substitute від INTERNAL_LIFT (per pair, per market) |
| **NFC1** | Широка категорія форми випуску (9 категорій) |
| **ORAL_GROUP** | 3 пероральні форми (тверді, рідкі, пролонговані) — взаємозамінні |
| **EXACT_MATCH** | Інші форми (ін'єкції, мазі, свічки) — замінюються тільки на ідентичні |
| **IQR** | Inter-Quartile Range; outlier якщо за межами `[Q1 - 1.5×IQR, Q3 + 1.5×IQR]` |
| **Dip test** | Hartigan's dip test на унімодальність розподілу (`p < 0.05` → multimodal) |
| **MEDIAN_SHARE_INTERNAL** | Медіана SHARE_INTERNAL across markets (після IQR-фільтрації) — **головний коефіцієнт `COEF_1`** |
| **AGG_SUBSTITUTE_SHARE** | LIFT-зважена частка substitute cross-market |

---

## ІНВАРІАНТИ (МАЮТЬ ВИКОНУВАТИСЯ)

| Інваріант | Де перевіряти |
|-----------|---------------|
| `0 ≤ SHARE_INTERNAL ≤ 1` | Phase A3 |
| `SHARE_INTERNAL + SHARE_LOST = 1` (per stockout event) | Phase A3 |
| `SUM(SUBSTITUTE_SHARE per stockout drug) ≈ 1` (per market) | Phase A4 |
| `0 ≤ MEDIAN_SHARE_INTERNAL ≤ 1` | Phase B4 |
| `0 ≤ COEF_1 ≤ 1` | Phase C1 |
| `UNIQUENESS_COEF = 1 - COEF_1` | Phase C1 |
| `SUM(AGG_SUBSTITUTE_SHARE per DRUGS_ID) ≈ 1` (cross-market) | Phase C2 |
| `MARKET_COUNT ≥ 20` для всіх записів у фінальних файлах | Phase C0 |

---

## PHASE A — Per-Market Processing

> Кожен крок A0–A5 виконується для одного ринку (CLIENT_ID) повністю в одному worker-процесі. Між кроками **немає disk I/O** — все в RAM.

### Phase A0: Discovery

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:** [`pipeline/discover_markets.py`](./pipeline/discover_markets.py)
**Підмодулі:** `config/paths.py`, `config/column_mapping.py`, `core/etl.py`
**Відповідає канонічному:** `cross_pharm_market_analysis/exec_scripts/01_did_processing/01_preproc.py`
**Версія алгоритму:** v1.0

#### Призначення
Просканувати папку `DATA_SETS/pd_ds_4_pres`, ідентифікувати валідні ринки через швидкий sniff (`nrows=3`), створити `markets_list.csv` для Phase A1.

#### Вхід / Вихід
- **Вхід:** `D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres\*.csv` (read-only, 207 файлів)
- **Вихід:**
  - `data/intermediate/00_preproc/markets_list.csv` — усі ринки зі STATUS (READY/EMPTY/MALFORMED) + REASON

#### Алгоритм (реалізований)

**Single-phase sniff (HDD-optimized):**

```python
def sniff_market_file(file_path):
    # 1. Розмір файлу через .stat()
    size_mb = file_path.stat().st_size / 1024**2

    # 2. Читання тільки nrows=3 (~швидко на HDD)
    try:
        df = pd.read_csv(file_path, sep=';', nrows=3)
    except EmptyDataError:
        return STATUS='EMPTY'
    except Exception as e:
        return STATUS='MALFORMED', reason=str(e)

    # 3. Empty check
    if len(df) == 0:
        return STATUS='EMPTY'

    # 4. Валідація 13 обов'язкових колонок
    missing = validate_raw_columns(df.columns)
    if missing:
        return STATUS='MALFORMED', reason=f'missing: {missing}'

    # 5. CLIENT_ID константність + конвертація в int
    client_ids = df['CLIENT_ID'].unique()
    if len(client_ids) != 1:
        return STATUS='MALFORMED', reason='CLIENT_ID not constant'
    client_id = int(client_ids[0])

    return STATUS='READY', client_id, ...
```

**Orchestrator:** glob-сканує файли, послідовно sniff кожен (~0.02s/файл), агрегує в DataFrame, сортує (READY → EMPTY → MALFORMED), пише CSV.

#### Структура `markets_list.csv`

| Колонка | Тип | Опис |
|---------|-----|------|
| `CLIENT_ID` | int (nullable) | З вмісту файлу. NULL для MALFORMED без читання |
| `FILE_NAME` | str | Базова назва файлу |
| `FILE_PATH` | str | Абсолютний шлях |
| `FILE_SIZE_MB` | float | Розмір файлу в MB (округлено) |
| `STATUS` | str | `READY` / `EMPTY` / `MALFORMED` |
| `REASON` | str | Причина не-READY (порожня для READY) |

#### Edge Cases (реалізовано)
| Ситуація | Поведінка |
|----------|-----------|
| `pd.errors.EmptyDataError` (порожній файл без header) | `STATUS=EMPTY`, `REASON='empty file (no header)'` |
| 0 рядків після header | `STATUS=EMPTY`, `REASON='0 data rows'` |
| Відсутня одна або більше з 13 колонок | `STATUS=MALFORMED`, `REASON='missing columns: [...]'` |
| CLIENT_ID не константний у nrows=3 | `STATUS=MALFORMED`, `REASON='CLIENT_ID not constant in first 3 rows: [...]'` |
| CLIENT_ID не int (наприклад string чи NaN) | `STATUS=MALFORMED`, `REASON='CLIENT_ID not integer'` |
| `read_csv` падає з іншою помилкою | `STATUS=MALFORMED`, `REASON='read_csv failed: ...'` |
| `.stat()` не вдається | `STATUS=MALFORMED`, `REASON='stat failed: ...'` |

#### Відмінності від канонічного (фактичні)
- **Sniff-only** (`nrows=3`) замість повного `read_csv` — швидкість 0.02s/файл vs ~10-30s/файл на HDD
- **3 виходи скорочені до 1**: тільки `markets_list.csv`. Прибрано `inn_list`, `nfc1_list`, `nfc2_list`, `drugs_list`, `markets_statistics`. `drugs_list` та повна статистика будуть зібрані під час Phase A1 (одне читання raw на worker)
- **`STATUS` колонка** для робочого процесу + UI
- **Без `print()`** — структурований dict для TUI; CLI-вивід тільки через `rich`
- **Sort order**: READY першими (за CLIENT_ID), потім EMPTY/MALFORMED (для зручності перегляду)
- **Exit code**: 0 якщо хоч один READY, 1 інакше

#### Підтверджена продуктивність (smoke-test 2026-04-27)
- **5 файлів** (255–945 MB кожен) → **0.10 сек**
- Екстраполяція на 207 файлів: ~**4-5 секунд** для повного discovery
- Disk I/O навантаження мінімальне (відкриваємо 207 файлів, читаємо ~6 KB кожен)

#### Що НЕ включено в Phase A0 (відкладено для Phase A1)
- Парсинг `PERIOD_ID` → дати → date range
- Підрахунок `competitors_count`, `drugs_count`, `inn_count`, `records_count`
- Збір унікальних `(DRUGS_ID, DRUGS_NAME)` для `drugs_list.csv`

Усі ці метрики зберуться **поетапно під час Phase A1** (кожен worker читає файл повністю в RAM, легко витягне свою частку → main процес агрегує наприкінці).

---

### Phase A1: Data Aggregation (ETL)

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:**
- [`core/etl.py`](./core/etl.py) — ETL функції
- [`pipeline/per_market.py`](./pipeline/per_market.py) — orchestrator
- [`config/stockout_params.py`](./config/stockout_params.py) — пороги (MIN_NOTSOLD, MAX_NOTSOLD)
**Відповідає канонічному:** `02_01_data_aggregation.py` + `etl_utils.py`
**Версія алгоритму:** v1.0

#### Призначення
Прочитати raw CSV одного ринку, виконати тижневу агрегацію з gap filling, NOTSOLD-фільтрацію, розрахувати market totals, зберегти один parquet per market.

#### Вхід / Вихід
- **Вхід:** `D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres\{CLIENT_ID}.csv`
- **Вихід:** `data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet`
- **Engine:** pyarrow, compression: snappy
- **Розмір:** ~3-5× менше CSV (на тестовому ринку 137 MB → 0.92 MB)

#### Алгоритм (реалізований)

```python
def process_market(client_id, file_path):
    # 1. Load full CSV в RAM (sequential read для HDD)
    df_raw = pd.read_csv(file_path, sep=';')

    # 2. Validation: CLIENT_ID match
    assert df_raw['CLIENT_ID'].iloc[0] == client_id

    # 3. Transformations
    df = rename_columns(df_raw, COLUMN_RENAME_MAP)  # ORG_ID→PHARM_ID, ...
    df = convert_numeric_columns(df, ['Q', 'V'])    # "12,5" → 12.5
    df = add_date_column(df, 'PERIOD_ID', 'Date', align_monday=True)

    # 4. Per-INN loop (sequential в межах worker)
    per_inn_results = []
    for inn_id in df['INN_ID'].unique():
        df_inn = df[df['INN_ID'] == inn_id]
        result = process_inn(df_inn, inn_id, client_id)
        if result is not None:
            per_inn_results.append(result)

    # 5. Concat & save
    df_market = pd.concat(per_inn_results)
    df_market.to_parquet(out_path, engine='pyarrow', compression='snappy')

    # 6. Return summary + drugs_df (для cross-market drugs_list)
    return {...}
```

#### Per-INN sub-algorithm

```python
def process_inn(df_inn, inn_id, client_id):
    # a. Gap filling per (PHARM_ID, DRUGS_ID) — CRITICAL for stockout!
    df_filled = fill_gaps(df_inn, group_cols=['PHARM_ID', 'DRUGS_ID'])

    # b. Weekly aggregation
    df_agg = aggregate_weekly(df_filled, group_cols=['PHARM_ID', 'DRUGS_ID', 'Date'])

    # c. Split target/competitors
    df_target      = df_agg[df_agg['PHARM_ID'] == client_id]
    df_competitors = df_agg[df_agg['PHARM_ID'] != client_id]

    # d. NOTSOLD per drug (на target)
    notsold = calculate_notsold_percent(df_target)
    df_target = df_target.merge(notsold, on=['PHARM_ID', 'DRUGS_ID'])

    # e. Filter drugs by NOTSOLD ∈ [0.20, 0.95]
    valid = notsold[(notsold['NOTSOLD_PERCENT'] >= 0.20) &
                    (notsold['NOTSOLD_PERCENT'] <= 0.95)]['DRUGS_ID']
    df_target      = df_target[df_target['DRUGS_ID'].isin(valid)]
    df_competitors = df_competitors[df_competitors['DRUGS_ID'].isin(valid)]

    if df_target.empty:
        return None  # INN skipped (no valid drugs)

    # f. MARKET_TOTALS з competitors per Date×DRUGS_ID
    market_totals = calculate_market_totals(df_competitors)

    # g. Merge target + market_totals
    df_final = df_target.merge(market_totals, on=['Date', 'DRUGS_ID'], how='left')
    df_final[['MARKET_TOTAL_DRUGS_PACK', 'MARKET_TOTAL_DRUGS_REVENUE']] = \
        df_final[['MARKET_TOTAL_DRUGS_PACK', 'MARKET_TOTAL_DRUGS_REVENUE']].fillna(0)

    return df_final
```

#### Структура вихідного parquet (13 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `PHARM_ID` | int64 | = CLIENT_ID (target тільки) |
| `DRUGS_ID` | int64 | Morion ID препарату |
| `Date` | datetime64[ns] | Понеділок тижня |
| `Q` | float64 | Кількість за тиждень (0 для gap-fill) |
| `V` | float64 | Виручка за тиждень (0 для gap-fill) |
| `DRUGS_NAME` | object | Назва препарату |
| `INN_NAME` | object | Назва INN |
| `INN_ID` | float64 ⚠️ | ID INN (NaN propagation в gap_fill → float) |
| `NFC1_ID` | object | NFC1 (форма) |
| `NFC_ID` | object | NFC2 (специфічна форма) |
| `NOTSOLD_PERCENT` | float64 | Доля тижнів з Q=0 (∈ [0.20, 0.95] після фільтра) |
| `MARKET_TOTAL_DRUGS_PACK` | float64 | Сума Q конкурентів |
| `MARKET_TOTAL_DRUGS_REVENUE` | float64 | Сума V конкурентів |

#### Ключові формули
| Формула | Опис |
|---------|------|
| `parse_period_id(YYYYNNNNN) → datetime` | Парсинг закодованої дати |
| `align_to_monday(date) → Monday(date)` | Вирівнювання по тижнях |
| `MARKET_TOTAL_DRUGS_PACK = sum(Q) для PHARM_ID != CLIENT_ID` | Ринок-конкуренти |
| `NOTSOLD_PERCENT = (тижні з Q=0) / (всього тижнів)` | Доля простоїв |

#### Інваріанти (перевірено на smoke-test)
- ✅ Кожна (Date, PHARM_ID, DRUGS_ID) комбінація унікальна після агрегації
- ✅ `Q` float ≥ 0
- ✅ `Date` — datetime64[ns]
- ✅ Q=0 рядки **присутні** (gap filling OK)
- ✅ `NOTSOLD_PERCENT ∈ [MIN, MAX]`
- ✅ MARKET_TOTAL без NaN
- ✅ Усі `PHARM_ID == CLIENT_ID` (target only)

#### Відмінності від канонічного
- **Не записуємо `inn_{INN_ID}_{CLIENT_ID}.csv`** — все в RAM, один parquet per market
- **Не записуємо `summary_*.csv` та `inn_summary_*.csv`** — не потрібні downstream
- **Parquet** замість CSV — компактніше, швидше, типізовано
- **Без `print()`** — структуровані dict + rich TUI
- **`drugs_df` повертається з `process_market`** — для cross-market drugs_list агрегації пізніше

#### Продуктивність (smoke-test 2026-04-27)
- Ринок 763807 (137 MB raw, найменший READY): **43.89 сек**
- 339K raw rows → 161K output rows
- 610 INN processed, 706 skipped (no valid drugs)
- 1,850 унікальних drugs після фільтра
- Прогноз 207 ринків паралельно × 6 workers: ~2-2.5 години

#### Відомі quirks
- **`INN_ID` dtype = float64** (а не int64) через NaN propagation у `fill_gaps` під час merge.
  - Не критично: всі downstream операції (`==`, `isin`, groupby) працюють.
  - За потреби — виправити в Phase A2 через `astype('int64')` після перевірки NaN.

---

### Phase A2: Stock-out Detection

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:**
- [`core/stockout.py`](./core/stockout.py) — algorithms (identify + validate)
- [`pipeline/per_market.py`](./pipeline/per_market.py) — orchestrator `process_market_stockout()`
**Відповідає канонічному:** `02_02_stockout_detection.py`
**Версія алгоритму:** v1.0 (1-в-1 з канонічного; слабкі місця методології задокументовано в [`_methods_issues.md`](./_methods_issues.md) ISSUE-006...012)

#### Призначення
Виявити періоди stock-out у target аптеці та валідувати їх за 3-рівневою схемою.

#### Вхід / Вихід
- **Вхід:** `data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet`
- **Вихід:** `data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet`
- **Engine:** pyarrow, compression: snappy

#### Алгоритм (реалізований)

```python
def process_market_stockout(client_id):
    df = pd.read_parquet(aggregated_parquet_path(client_id))

    events = []
    counter = 1

    for inn_id, df_inn in df.groupby("INN_ID"):
        for drug_id, df_drug in df_inn.groupby("DRUGS_ID"):
            # 1. Identify all Q=0 sequences
            stockout_periods = identify_stockout_periods(df_drug)

            for period in stockout_periods:
                # 2. Define PRE-period (4 weeks, with 1 week gap)
                pre_end   = period["start"] - timedelta(days=7)
                pre_start = pre_end - timedelta(weeks=3)  # 4 weeks total

                # 3. 3-level validation
                is_valid, reason, details = validate_stockout_event(
                    df_drug, df_inn, period["start"], period["end"],
                    pre_start, pre_end, min_pre_weeks=4,
                )

                if is_valid:
                    events.append({
                        "EVENT_ID": f"{client_id}_{inn_id}_{counter:04d}",
                        ...
                    })
                    counter += 1

    save_parquet(events, output_path)
```

#### `identify_stockout_periods` — vectorized

Використовує `diff() + cumsum()` для O(N) пошуку послідовних Q=0:

```python
is_zero = (df_sorted["Q"] == 0).astype(int)
state_change = is_zero.diff().fillna(is_zero.iloc[0]).ne(0).cumsum()
# Кожна група послідовних однакових станів отримує unique ID

zero_groups = df_sorted[is_zero == 1].groupby(state_change)
# Беремо лише групи Q=0, фільтруємо за тривалістю
```

#### `validate_stockout_event` — 3-level validation

Детальний опис кожного рівня — у канонічному `docs/01_did_processing/02_STOCKOUT_DETECTION.md`. Коротко:

| Level | Питання | Перевірка | Aggregation level |
|-------|---------|-----------|-------------------|
| **1** | Чи активна INN група під час stockout? | `sum(MARKET_TOTAL_DRUGS_PACK для INN) > 0` | INN |
| **2** | Чи були продажі цього drug у PRE? | `Q > 0` хоча б в один тиждень PRE & `pre_weeks >= 4` | Drug |
| **3** | Чи продавали конкуренти цей drug? | `sum(MARKET_TOTAL_DRUGS_PACK для drug) > 0` | Drug |

Reasons of rejection: `'no_market_activity'`, `'no_pre_sales'`, `'no_competitors'`.

#### PRE-period definition

```
                                                        час →
─── PRE (4 weeks) ──── 1 week gap ──── STOCKOUT period ──── ...
   [pre_start...pre_end]              [stockout_start...stockout_end]
```

```python
pre_end   = stockout_start - timedelta(days=7)
pre_start = pre_end - timedelta(weeks=MIN_PRE_PERIOD_WEEKS - 1)  # 4 weeks total
```

Gap = 7 днів запобігає забрудненню PRE даними початку stockout.

#### Структура вихідного parquet (14 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `EVENT_ID` | object | `{CLIENT_ID}_{INN_ID}_{0001}` (4-digit counter per market) |
| `CLIENT_ID` | int64 | ID цільової аптеки |
| `INN_ID` | int64 | ID INN групи |
| `INN_NAME` | object | Назва INN |
| `DRUGS_ID` | int64 | Morion ID препарату |
| `DRUGS_NAME` | object | Назва препарату |
| `NFC1_ID` | object | Форма випуску (для Phase A3 NFC compatibility) |
| `STOCKOUT_START` | datetime64[ns] | Перший тиждень Q=0 |
| `STOCKOUT_END` | datetime64[ns] | Останній тиждень Q=0 |
| `STOCKOUT_WEEKS` | int64 | Тривалість stockout |
| `PRE_START` | datetime64[ns] | Початок PRE-періоду |
| `PRE_END` | datetime64[ns] | Кінець PRE-періоду |
| `PRE_WEEKS` | int64 | Кількість тижнів PRE |
| `PRE_AVG_Q` | float64 | Середній Q у PRE (baseline для DiD) |

#### Ключові формули

| Формула | Опис |
|---------|------|
| `pre_end = stockout_start - 7 days` | 1-тижневий gap |
| `pre_start = pre_end - (MIN_PRE_PERIOD_WEEKS - 1) × 7 days` | PRE = 4 тижні |
| `pre_avg_q = pre_sales / pre_weeks` | Baseline для DiD |
| `market_during_inn = sum(MARKET_TOTAL_DRUGS_PACK для INN у DURING)` | Level 1 |
| `pre_sales = sum(Q у PRE для drug у target)` | Level 2 |
| `competitors_sales = sum(MARKET_TOTAL_DRUGS_PACK для drug у DURING)` | Level 3 |

#### Інваріанти (перевірено на smoke-test)
- ✅ `STOCKOUT_END >= STOCKOUT_START`
- ✅ `PRE_END < STOCKOUT_START` (gap respected)
- ✅ `STOCKOUT_WEEKS >= 1`
- ✅ `PRE_WEEKS >= 4`
- ✅ `PRE_AVG_Q > 0` (Level 2 гарантує)
- ✅ EVENT_IDs унікальні per market

#### Edge Cases
| Ситуація | Поведінка |
|----------|-----------|
| Empty `aggregated.parquet` | `status='no_data'`, error message |
| Drug без stockout (всі Q>0) | Skip drug |
| Stockout на початку даних (PRE неможливий) | Reject `no_pre_sales` (pre_weeks < 4) |
| Stockout до кінця даних | Зберігається; POST буде валідовано в Phase A3 |
| 0 valid events for whole market | Empty parquet з правильною схемою |

#### Продуктивність (smoke-test 2026-04-27 на 763807)
- Вхід: 161,636 рядків × 13 колонок (aggregated.parquet)
- Вихід: 8,581 events (валідних)
- Validation rate: 64.6% (lower than canonical ~80% — малий ринок)
- 19.22 секунд

#### Відмінності від канонічного
- **Вхід — parquet** (не CSV per INN)
- **Вихід — parquet** (не CSV)
- **Дати — datetime64** (не string YYYY-MM-DD)
- **14 колонок** (без NFC_ID, MARKET_DURING_Q)
- **Без окремих stats CSV** (метрики в return dict)
- **Без `print()`** — rich TUI
- INN_ID cast `float64 → int64` через quirk Phase A1 (ISSUE-002)

---

### Phase A3: DiD Analysis

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:**
- [`core/did.py`](./core/did.py) — DiD utilities + main calculation (з ISSUE-013 FIX)
- [`core/nfc.py`](./core/nfc.py) — NFC compatibility (1-в-1 з канонічного)
- [`pipeline/per_market.py`](./pipeline/per_market.py) — orchestrator `process_market_did()`
**Відповідає канонічному:** `02_03_did_analysis.py`
**Версія алгоритму:** v1.1 (з ISSUE-013 FIX — див. [_methods_issues.md](./_methods_issues.md))

#### Призначення
Розрахувати DiD-ефект для кожної stockout події: визначити POST, ідентифікувати substitutes (NFC + Phantom), розрахувати MARKET_GROWTH та LIFT для substitutes і LOST_SALES для target → SHARE_INTERNAL, SHARE_LOST.

#### Вхід / Вихід
- **Вхід:**
  - `data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet`
  - `data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet`
- **Вихід:**
  - `data/intermediate/01_per_market/{CLIENT_ID}/did_events.parquet` (event-level metrics)
  - `data/intermediate/01_per_market/{CLIENT_ID}/substitute_pairs.parquet` (per-pair LIFT)

#### Алгоритм (реалізований)

```python
def process_market_did(client_id):
    df_agg     = pd.read_parquet(aggregated.parquet)
    df_events  = pd.read_parquet(stockout_events.parquet)

    inn_data = {inn_id: grp for inn_id, grp in df_agg.groupby('INN_ID')}

    for inn_id, inn_events in df_events.groupby('INN_ID'):
        df_inn = inn_data[inn_id]
        drug_index = {d: g for d, g in df_inn.groupby('DRUGS_ID')}

        for event in inn_events.iterrows():
            # 1. POST-period
            post_start, post_end, post_weeks, status = define_post_period(...)
            if status != 'valid': reject('no_post_period')

            # 2. Substitutes: NFC + Phantom filters
            valid_subs = find_valid_substitutes(drug_index, target_id, target_nfc1, ...)
            if not valid_subs: counter('no_substitutes')  # Still process

            # 3. DiD calculation (з ISSUE-013 FIX)
            event_metrics, sub_pairs = calculate_did_for_event(...)

            # 4. Effect threshold
            if event_metrics['TOTAL_EFFECT'] < 0.001: reject('no_effect')

            # 5. Append
            did_events.append(event_row)
            sub_pairs_all.extend(pair_rows)

    save_parquet(did_events, 'did_events.parquet')
    save_parquet(sub_pairs_all, 'substitute_pairs.parquet')
```

#### Sub-algorithm: `find_valid_substitutes`

```python
def find_valid_substitutes(drug_index, target_drug_id, target_nfc1, stockout_start, stockout_end):
    valid = []
    for drug_id, df_sub in drug_index.items():
        if drug_id == target_drug_id: continue
        sub_nfc1 = df_sub['NFC1_ID'].iloc[0]

        # Filter 1: NFC compatibility
        if not is_compatible(target_nfc1, sub_nfc1): continue

        # Filter 2: Phantom — substitute мав дані під час stockout
        df_during = df_sub[(df_sub['Date'] >= stockout_start) & (df_sub['Date'] <= stockout_end)]
        if df_during.empty: continue

        valid.append({SUBSTITUTE_DRUGS_ID, SAME_NFC1, ...})
    return valid
```

#### Sub-algorithm: `calculate_did_for_event` (з ISSUE-013 FIX)

```python
def calculate_did_for_event(df_inn, drug_index, target_drug_id, valid_subs, ...):
    # 1. MARKET_GROWTH (INN-level)
    market_pre    = sum(MARKET_TOTAL_DRUGS_PACK across INN in PRE)
    market_during = sum(MARKET_TOTAL_DRUGS_PACK across INN in DURING)
    market_growth = market_during / market_pre  # if market_pre >= 1.0

    # 2. INTERNAL_LIFT (sum of substitute LIFTs)
    sub_pairs = []
    for sub in valid_subs:
        sales_pre    = sum(Q for substitute in PRE)
        sales_during = sum(Q for substitute in DURING)
        expected     = max(0, sales_pre × market_growth)
        lift         = max(0, sales_during - expected)
        sub_pairs.append({..., LIFT: lift})
    internal_lift = sum(sp['LIFT'] for sp in sub_pairs)

    # 3. LOST_SALES — ⚠️ FIXED (ISSUE-013):
    #   canonical: comp_pre = max(0, market_total_pre - target_pre)  ← BUG
    #   our fix:   comp_pre = market_total_pre  (already competitors-only)
    df_target_drug = drug_index.get(target_drug_id)
    comp_pre    = df_target_drug[PRE]['MARKET_TOTAL_DRUGS_PACK'].sum()    # competitors only
    comp_during = df_target_drug[DURING]['MARKET_TOTAL_DRUGS_PACK'].sum()
    comp_expected = max(0, comp_pre × market_growth)
    lost_sales    = max(0, comp_during - comp_expected)

    # 4. Shares
    total_effect   = internal_lift + lost_sales
    share_internal = internal_lift / total_effect  # if total_effect >= 0.001
    share_lost     = lost_sales / total_effect

    return event_metrics, sub_pairs
```

#### Ключові формули

| Формула | Опис |
|---------|------|
| `MARKET_GROWTH = MARKET_DURING / MARKET_PRE` | Volume ratio PRE→DURING (INN-level) |
| `EXPECTED_substitute = sales_pre × MARKET_GROWTH` | Counterfactual для substitute |
| `LIFT_substitute = max(0, sales_during - expected)` | Додатковий попит від stockout |
| `INTERNAL_LIFT = Σ LIFT_substitutes` | Сума LIFT всіх substitutes |
| `comp_pre = MARKET_TOTAL_DRUGS_PACK для target_drug у PRE` | ⚠️ FIXED: без віднімання target_pre |
| `LOST_SALES = max(0, comp_during - comp_pre × MARKET_GROWTH)` | LIFT конкурентів |
| `SHARE_INTERNAL = INTERNAL_LIFT / TOTAL_EFFECT` | Частка попиту, що залишилась |
| `SHARE_LOST = 1 - SHARE_INTERNAL` | Частка попиту до конкурентів |

#### NFC Compatibility Filter (`core/nfc.py`)

| Правило | Логіка |
|---------|--------|
| EXCLUDED форми (`Не предназначенные...`) | Завжди False |
| Exact match (form_a == form_b) | True |
| Обидві в ORAL_GROUP | True |
| Інше | False |

ORAL_GROUP:
- Пероральные твердые обычные
- Пероральные жидкие обычные
- Пероральные твердые длительно действующие

#### Структура `did_events.parquet` (20 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `EVENT_ID` | object | FK to stockout_events |
| `CLIENT_ID` | int64 | |
| `INN_ID` | int64 | |
| `DRUGS_ID`, `DRUGS_NAME`, `NFC1_ID` | int/obj | Stockout drug |
| `POST_START`, `POST_END` | datetime64 | POST-period |
| `POST_WEEKS` | int | Завжди = `MIN_POST_PERIOD_WEEKS` (4) для valid |
| `POST_STATUS` | object | Завжди 'valid' (інші відфільтровані) |
| `MARKET_PRE`, `MARKET_DURING` | float64 | INN-level суми |
| `MARKET_GROWTH` | float64 | DURING/PRE volume ratio |
| `INTERNAL_LIFT`, `LOST_SALES`, `TOTAL_EFFECT` | float64 | DiD метрики |
| `SHARE_INTERNAL`, `SHARE_LOST` | float64 | Частки ∈ [0, 1] |
| `SUBSTITUTES_COUNT`, `SUBSTITUTES_WITH_LIFT` | int | Метрики substitutes |

#### Структура `substitute_pairs.parquet` (14 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `EVENT_ID` | object | FK to did_events |
| `CLIENT_ID`, `INN_ID` | int64 | |
| `TARGET_DRUGS_ID`, `TARGET_DRUGS_NAME`, `TARGET_NFC1_ID` | | Stockout drug |
| `SUBSTITUTE_DRUGS_ID`, `SUBSTITUTE_DRUGS_NAME`, `SUBSTITUTE_NFC1_ID` | | Замінник |
| `SAME_NFC1` | bool | Чи та сама форма |
| `SALES_PRE`, `SALES_DURING` | float64 | Q substitute у періодах |
| `EXPECTED` | float64 | sales_pre × market_growth |
| `LIFT` | float64 | max(0, sales_during - expected) ← **для Phase A4** |

#### Інваріанти (перевірено на smoke-test)
- ✅ `SHARE_INTERNAL + SHARE_LOST = 1.0` (max diff: 0.000000 на 5350 events)
- ✅ `0 ≤ SHARE_INTERNAL, SHARE_LOST ≤ 1`
- ✅ `TOTAL_EFFECT >= MIN_TOTAL_FOR_SHARE` (0.001)
- ✅ `LIFT >= 0` (за визначенням `max(0, ...)`)
- ✅ Cross-file: `INTERNAL_LIFT (did_events) == sum(LIFT) (substitute_pairs)` per event (max diff 0.0002 — rounding)
- ✅ EVENT_IDs у substitute_pairs ⊂ EVENT_IDs у did_events (FK constraint)
- ✅ TARGET != SUBSTITUTE
- ✅ POST_STATUS == 'valid' для всіх записів (інші відфільтровані)

#### Edge Cases
| Ситуація | Обробка |
|----------|---------|
| MARKET_PRE < 1 (відсутні дані PRE на ринку) | MARKET_GROWTH = 1.0 (нейтрально) |
| TOTAL_EFFECT < 0.001 | Reject `no_effect` |
| Жодного валідного substitute | Counter `no_substitutes` (informational), still processed; INTERNAL_LIFT=0; LOST_SALES може бути > 0 → подія може пройти |
| POST не визначено | Reject `no_post_period` (no_recovery / gap_too_large / insufficient_data) |
| target_drug нема в drug_index | comp_pre = comp_during = 0 → LOST_SALES = 0 |

#### Продуктивність (smoke-test 2026-04-27 на 763807)
- Вхід: 8,581 events
- Вихід: 5,350 valid events (62.3%) + 28,621 substitute pairs
- 64.95 sec
- Avg pairs per event: 5.3
- SAME_NFC1 ratio: 82.8%

#### Ключові відмінності від канонічного

1. **🔴 ISSUE-013 FIX:** `comp_pre = market_total_pre` (не `max(0, market_total_pre - target_pre)`). Математично коректно. Документовано.
2. **Вхід — parquet** (не CSV per INN); **Вихід — parquet** (не CSV)
3. **Дати — datetime64** (не string)
4. **2 файли замість 5**: did_events + substitute_pairs (без summary.csv, drugs_summary.csv, metadata.csv)
5. **substitute_pairs включає LIFT** — оптимізація для Phase A4 (не перераховувати)
6. **Без NFC1 декомпозиції** (LIFT_SAME_NFC1, LIFT_DIFF_NFC1, SHARE_SAME_NFC1, SHARE_DIFF_NFC1) — не потрібно для наших фінальних файлів
7. **Без CRITICAL/SUBSTITUTABLE/MODERATE класифікації** — не потрібно
8. **Без ThreadPool** (CPU без HT) — sequential per-INN
9. **Без `print()`** — rich TUI
10. INN_ID auto-cast `float64 → int64` через quirk Phase A1 (ISSUE-002)

---

### Phase A4: Substitute Analysis

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:** [`pipeline/per_market.py::process_market_substitutes`](./pipeline/per_market.py)
**Відповідає канонічному:** `02_04_substitute_analysis.py`
**Версія алгоритму:** v1.0 (значно простіша за канонічний завдяки оптимізації Q-A3.3)

#### Призначення
Агрегувати substitutes per (stockout_drug, substitute_drug) cross-events у межах одного ринку, розрахувати SUBSTITUTE_SHARE та SUBSTITUTE_RANK.

#### Вхід / Вихід
- **Вхід:**
  - `data/intermediate/01_per_market/{CLIENT_ID}/substitute_pairs.parquet` (Phase A3 — LIFT уже є)
  - `data/intermediate/01_per_market/{CLIENT_ID}/stockout_events.parquet` (для INN_NAME lookup)
- **Вихід:**
  - `data/intermediate/01_per_market/{CLIENT_ID}/substitute_shares.parquet`

#### КЛЮЧОВА ОПТИМІЗАЦІЯ vs канонічного

Канонічна Phase 4 для кожної з тисяч подій **повторно перераховує LIFT** для substitutes (читає aggregated.parquet, фільтрує per drug, рахує sales_pre, sales_during, expected, lift). Це O(events × substitutes × data_lookups) — повільно.

Наша Phase A4 використовує **LIFT, що вже збережений** у `substitute_pairs.parquet` (Q-A3.3). Просто `groupby + sum`. O(pairs).

**Результат:** 0.18 sec замість десятків секунд.

#### Алгоритм (реалізований)

```python
def process_market_substitutes(client_id):
    df_pairs  = pd.read_parquet('substitute_pairs.parquet')   # has LIFT
    df_events = pd.read_parquet('stockout_events.parquet')

    # 1. INN_NAME lookup (бо substitute_pairs має тільки INN_ID)
    inn_name_map = df_events[['INN_ID','INN_NAME']].drop_duplicates().set_index('INN_ID')['INN_NAME']
    df_pairs['INN_NAME'] = df_pairs['INN_ID'].map(inn_name_map)

    # 2. Aggregate per (stockout, substitute): sum LIFT + count events
    df_agg = df_pairs.groupby([
        'CLIENT_ID', 'INN_ID', 'INN_NAME',
        'TARGET_DRUGS_ID', 'TARGET_DRUGS_NAME', 'TARGET_NFC1_ID',
        'SUBSTITUTE_DRUGS_ID', 'SUBSTITUTE_DRUGS_NAME', 'SUBSTITUTE_NFC1_ID',
        'SAME_NFC1',
    ], as_index=False).agg(
        TOTAL_LIFT=('LIFT', 'sum'),
        EVENTS_COUNT=('EVENT_ID', 'count'),
    )

    # 3. Rename TARGET_* → STOCKOUT_*
    df_agg = df_agg.rename(columns={
        'TARGET_DRUGS_ID':       'STOCKOUT_DRUG_ID',
        'TARGET_DRUGS_NAME':     'STOCKOUT_DRUG_NAME',
        'TARGET_NFC1_ID':        'STOCKOUT_NFC1_ID',
        'SUBSTITUTE_DRUGS_ID':   'SUBSTITUTE_DRUG_ID',
        'SUBSTITUTE_DRUGS_NAME': 'SUBSTITUTE_DRUG_NAME',
    })

    # 4. Zero-LIFT filter
    df_agg = df_agg[df_agg['TOTAL_LIFT'] > 0].copy()

    # 5. INTERNAL_LIFT per stockout drug (sum after filter)
    internal = df_agg.groupby('STOCKOUT_DRUG_ID')['TOTAL_LIFT'].sum().rename('INTERNAL_LIFT').reset_index()
    df_agg = df_agg.merge(internal, on='STOCKOUT_DRUG_ID', how='left')

    # 6. SUBSTITUTE_SHARE — decimal (0-1)
    df_agg['SUBSTITUTE_SHARE'] = df_agg['TOTAL_LIFT'] / df_agg['INTERNAL_LIFT']

    # 7. SUBSTITUTE_RANK (1 = highest within stockout drug)
    df_agg = df_agg.sort_values(['STOCKOUT_DRUG_ID', 'SUBSTITUTE_SHARE'], ascending=[True, False])
    df_agg['SUBSTITUTE_RANK'] = df_agg.groupby('STOCKOUT_DRUG_ID')['SUBSTITUTE_SHARE'].rank(method='first', ascending=False).astype(int)

    save_parquet(df_agg, 'substitute_shares.parquet')
```

#### Структура `substitute_shares.parquet` (15 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `CLIENT_ID` | int64 | Market ID |
| `INN_ID` | int64 | INN |
| `INN_NAME` | str | (lookup з stockout_events) |
| `STOCKOUT_DRUG_ID` | int64 | Препарат що був відсутній |
| `STOCKOUT_DRUG_NAME` | str | |
| `STOCKOUT_NFC1_ID` | str | |
| `SUBSTITUTE_DRUG_ID` | int64 | Замінник |
| `SUBSTITUTE_DRUG_NAME` | str | |
| `SUBSTITUTE_NFC1_ID` | str | |
| `SAME_NFC1` | bool | |
| `TOTAL_LIFT` | float64 | sum(LIFT) across events for this pair |
| `INTERNAL_LIFT` | float64 | sum(TOTAL_LIFT) within stockout drug (після Zero-LIFT filter) |
| `SUBSTITUTE_SHARE` | float64 | TOTAL_LIFT / INTERNAL_LIFT (**decimal 0-1**) |
| `EVENTS_COUNT` | int64 | Скільки подій містили цю пару |
| `SUBSTITUTE_RANK` | int64 | Ранг у межах stockout drug (1 = найвищий SHARE) |

#### Ключові формули

| Формула | Опис |
|---------|------|
| `TOTAL_LIFT = sum(LIFT for this pair across events)` | Сумарний LIFT пари |
| `INTERNAL_LIFT_per_stockout = sum(TOTAL_LIFT for surviving substitutes)` | Після zero-filter |
| `SUBSTITUTE_SHARE = TOTAL_LIFT / INTERNAL_LIFT` | **decimal (0-1)** |
| `SUBSTITUTE_RANK = rank within stockout drug, descending by SHARE` | 1 = top |

#### Інваріанти (перевірено на smoke-test)
- ✅ `STOCKOUT_DRUG_ID ≠ SUBSTITUTE_DRUG_ID`
- ✅ `TOTAL_LIFT > 0` (всі zero-LIFT відфільтровано)
- ✅ `TOTAL_LIFT ≤ INTERNAL_LIFT` (sanity check)
- ✅ `SUBSTITUTE_SHARE ∈ (0, 1]`
- ✅ **`SUM(SUBSTITUTE_SHARE per STOCKOUT_DRUG_ID) = 1.0`** (max diff: 0.0000050)
- ✅ `RANK consistency`: 1, 2, 3, ... без gaps в межах stockout drug
- ✅ EVENTS_COUNT ≥ 1
- ✅ No NaN у critical cols

#### Edge Cases
| Ситуація | Поведінка |
|----------|-----------|
| substitute_pairs.parquet порожній | `status='no_data'` |
| Усі пари відфільтровано (zero-LIFT) | Empty parquet з правильною схемою; `status='no_data'` |
| 1 substitute для drug | SHARE = 1.0, RANK = 1 |
| Multiple substitutes з однаковим SHARE | RANK через `method='first'` (consecutive ranks без ties) |

#### Продуктивність (smoke-test 2026-04-27 на 763807)
- Вхід: 28,621 pairs (Phase A3)
- Aggregation → 5,842 unique pairs
- Zero-LIFT filter → 4,873 pairs (-969)
- **0.18 sec** (значно швидше за канонічний завдяки відсутності re-computation)

#### Стат результати
```
Stockout drugs: 833    Unique substitutes: 1,178
Avg subs/drug:  5.85   SAME_NFC1 ratio: 81.3%
Avg SHARE rank=1: 0.629  Median EVENTS_COUNT: 4
```

#### Відмінності від канонічного
1. **Без re-computation LIFT** — використовуємо існуючий LIFT з Phase A3 (Q-A3.3 optimization)
2. **Без ThreadPool** — vectorized aggregation швидкий
3. **SUBSTITUTE_SHARE як decimal (0-1)** замість percentage (0-100) — узгоджено з фінальними файлами
4. **Без NFC1 декомпозиції** (LIFT_SAME_NFC1, LIFT_DIFF_NFC1)
5. **SUBSTITUTE_RANK додано напряму** (canonical додає в Phase 5)
6. **Без stat файлів** (summary, metadata) — метрики в return dict

---

### Phase A5: Save Intermediate

**Статус:** ⏳ TBD (буде реалізовано в Кроку 6)
**Реалізація:** `pipeline/per_market.py`

#### Призначення
Зберегти результати Phase A для кожного ринку у 2 плоских CSV для подальшої cross-market агрегації.

#### Output
```
data/intermediate/01_per_market/{CLIENT_ID}/
├── sub_coef.csv     # CLIENT_ID, DRUGS_ID, DRUGS_NAME, INN_ID, INN_NAME, NFC1_ID,
│                    # EVENTS_COUNT, INTERNAL_LIFT, LOST_SALES, TOTAL_EFFECT,
│                    # SHARE_INTERNAL, SHARE_LOST
└── sub_drugs.csv    # CLIENT_ID, STOCKOUT_DRUG_ID, STOCKOUT_DRUG_NAME, INN_ID,
                     # INN_NAME, NFC1_ID, SUBSTITUTE_DRUG_ID, SUBSTITUTE_DRUG_NAME,
                     # SUBSTITUTE_NFC1_ID, SAME_NFC1, SUBSTITUTE_SHARE, SUBSTITUTE_RANK
```

#### Відмінності від канонічного
- Структура **спрощена** vs `sub_coef_{ID}.csv` канонічного:
  - Прибрано: `LIFT_SAME_NFC1`, `LIFT_DIFF_NFC1`, `SHARE_SAME_NFC1`, `SHARE_DIFF_NFC1`, `CLASSIFICATION`, `RECOMMENDATION`, `TOTAL_STOCKOUT_WEEKS`, `FIRST_STOCKOUT_DATE`, `LAST_STOCKOUT_DATE`, `TOTAL_LIFT_SAME_NFC1`, `TOTAL_LIFT_DIFF_NFC1`
  - Залишено: ідентифікатори + `EVENTS_COUNT, INTERNAL_LIFT, LOST_SALES, TOTAL_EFFECT, SHARE_INTERNAL, SHARE_LOST`

---

## PHASE B — Cross-Market Aggregation

### Phase B: Cross-Market Aggregation (B1 + B2 + B3 + B4 в одному модулі)

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:** [`pipeline/cross_market.py`](./pipeline/cross_market.py) (~310 рядків)
**Відповідає канонічному:** `02_substitution_coefficients/01_data_preparation.py` + `02_01_statistical_analysis.py` (значно спрощено vs 2617 рядків канонічного)
**Версія алгоритму:** v1.0

#### Призначення
Зібрати did_events.parquet з усіх ринків і для кожного DRUGS_ID розрахувати:
- MARKET_COUNT_TOTAL / MARKET_COUNT_CLEAN
- MEDIAN_SHARE_INTERNAL (після IQR-фільтрації)
- DRUG_CLASS (UNIMODAL / MULTIMODAL через Hartigan dip test)

#### Вхід / Вихід
- **Вхід:**
  - `data/intermediate/01_per_market/{ID}/did_events.parquet` (всі готові ринки)
  - `data/intermediate/01_per_market/{ID}/stockout_events.parquet` (тільки для INN_NAME lookup)
- **Вихід:** `data/intermediate/02_cross_market/drug_statistics.parquet` (10 cols)

#### Алгоритм (повний реалізований)

```python
def run_cross_market():
    # 1. Знайти всі ринки з did_events.parquet
    market_dirs = find_market_dirs()

    # 2. Зібрати DiD events
    df_did = load_did_events_all(market_dirs)  # concat усіх

    # 3. INN_NAME lookup з stockout_events
    inn_name_lookup = build_inn_name_lookup(market_dirs)

    # 4. Per-market drug aggregation: ratio of sums
    per_market_drug = df_did.groupby(['CLIENT_ID', 'DRUGS_ID']).agg(
        INTERNAL_LIFT=('INTERNAL_LIFT', 'sum'),
        LOST_SALES=('LOST_SALES', 'sum'),
        TOTAL_EFFECT=('TOTAL_EFFECT', 'sum'),
        EVENTS_COUNT=('EVENT_ID', 'count'),
        DRUGS_NAME=('DRUGS_NAME', 'first'),
        INN_ID=('INN_ID', 'first'),
        NFC1_ID=('NFC1_ID', 'first'),
    ).reset_index()
    per_market_drug['SHARE_INTERNAL'] = (
        per_market_drug['INTERNAL_LIFT'] / per_market_drug['TOTAL_EFFECT']
    )

    # 5. Cross-market: per drug → IQR + dip test + median
    rows = []
    for drug_id, group in per_market_drug.groupby('DRUGS_ID'):
        shares = group['SHARE_INTERNAL'].dropna().to_numpy()
        clean_shares = iqr_outlier_filter(shares, k=1.5)
        drug_class, dip_p = classify_modality(clean_shares, alpha=0.05, min_n=4)
        rows.append({
            'DRUGS_ID': drug_id,
            'DRUGS_NAME': ...,
            'INN_ID': inn_id,
            'INN_NAME': inn_name_lookup.get(inn_id, ''),
            'NFC1_ID': ...,
            'MARKET_COUNT_TOTAL': len(shares),
            'MARKET_COUNT_CLEAN': len(clean_shares),
            'MEDIAN_SHARE_INTERNAL': float(np.median(clean_shares)),
            'DRUG_CLASS': drug_class,
            'DIP_PVALUE': dip_p,
        })

    save_parquet(pd.DataFrame(rows), 'drug_statistics.parquet')
```

#### Sub-algorithm: `iqr_outlier_filter`

```python
def iqr_outlier_filter(values, k=1.5):
    if len(values) == 0: return values
    q1, q3 = np.percentile(values, [25, 75])
    iqr = q3 - q1
    mask = (values >= q1 - k*iqr) & (values <= q3 + k*iqr)
    return values[mask]
```

#### Sub-algorithm: `classify_modality` (Hartigan dip test)

```python
def classify_modality(clean_values, alpha=0.05, min_n=4):
    if len(clean_values) < min_n:
        return 'UNIMODAL', 1.0
    from diptest import diptest
    dip, p_value = diptest(clean_values)
    return ('MULTIMODAL' if p_value < alpha else 'UNIMODAL'), float(p_value)
```

H0: розподіл унімодальний. Якщо p < alpha → відхиляємо H0 → MULTIMODAL.

#### Структура `drug_statistics.parquet` (10 колонок)

| Колонка | Тип | Опис |
|---------|-----|------|
| `DRUGS_ID` | int64 | |
| `DRUGS_NAME` | str | |
| `INN_ID` | int64 | |
| `INN_NAME` | str | (lookup з stockout_events) |
| `NFC1_ID` | str | |
| `MARKET_COUNT_TOTAL` | int | На скільки ринках drug мав valid DiD events |
| `MARKET_COUNT_CLEAN` | int | Після IQR фільтра |
| `MEDIAN_SHARE_INTERNAL` | float | Медіана після IQR — це наш `COEF_1` у Phase C |
| `DRUG_CLASS` | str | `UNIMODAL` / `MULTIMODAL` |
| `DIP_PVALUE` | float | p-value Hartigan dip test (для прозорості) |

#### Параметри

| Параметр | Значення | Джерело |
|----------|----------|---------|
| `IQR_MULTIPLIER` | 1.5 | Tukey стандарт |
| `DIP_TEST_ALPHA` | 0.05 | Стандартний рівень значущості |
| `MIN_N_FOR_DIPTEST` | 4 | Менше → default UNIMODAL |

#### Інваріанти (перевірено на smoke-test)
- ✅ No NaN in MEDIAN_SHARE_INTERNAL
- ✅ MEDIAN ∈ [0, 1]
- ✅ MARKET_COUNT_TOTAL >= 1
- ✅ MARKET_COUNT_CLEAN <= MARKET_COUNT_TOTAL
- ✅ MARKET_COUNT_CLEAN >= 1 (IQR не зриває все)
- ✅ DRUG_CLASS only {UNIMODAL, MULTIMODAL}
- ✅ DIP_PVALUE ∈ [0, 1]
- ✅ Унікальність DRUGS_ID
- ✅ INN_NAME populated через lookup

#### Edge Cases
| Ситуація | Поведінка |
|----------|-----------|
| Drug на 1 ринку | IQR не змінює, dip test → UNIMODAL (n<4); SHARE = single value |
| Усі SHARE однакові | IQR → той самий масив; dip test → UNIMODAL; median = value |
| IQR прибрав ВСЕ (n=1, IQR=0) | Fallback: використовуємо raw shares |
| diptest crash на edge case | except → UNIMODAL, p=1.0 |
| TOTAL_EFFECT = 0 в per-market drug aggregation | dropna() — пара виключається |

#### Продуктивність (smoke-test 2026-04-27)
- 5 ринків, 133K events → 11.8K per-market drug pairs → 5,120 unique drugs
- 99.4% UNIMODAL, 0.6% MULTIMODAL (мала кількість через 5 ринків)
- 308 drugs з outliers (5%)
- **1.74 секунди** загалом

#### Відмінності від канонічного
- **Один файл** замість 3 (значно простіше)
- **Без WEIGHTED_MEAN, STD, CI_95, RELIABILITY** (не потрібні для наших фінальних 4 файлів)
- **Без COVERAGE_CLUSTER** (HIGH/MEDIUM/LOW/INSUFFICIENT) — фільтр через MARKET_COUNT >= 20 у Phase C
- **Без Scenario A валідного фільтра** (нам не потрібно — у Phase C інший фільтр)
- **Без pipeline funnel + cross-table distribution** (інформативні XLSX)
- **Parquet** замість CSV/XLSX
- **+ Hartigan dip test для UNIMODAL/MULTIMODAL** — нова функціональність нашого проекту
- **Ratio of sums** для per-market drug SHARE (як у канонічному)


### Phase B: Updates у v2.0 та v2.1 (2026-04-29 / 2026-05-01)

Початкова версія Phase B (v1, описана вище) дала 10 колонок у `drug_statistics.parquet`
з `MEDIAN_SHARE_INTERNAL` як основою для COEF_1. Подальші ітерації додали важливі
методологічні розширення.

#### v2.0 — Перехід median → mean + декомпозиція (Step 13, 2026-04-29)

Виявлено, що медіана не репрезентативна для MULTIMODAL препаратів (приклад: ДИКЛОКАИН,
DRUGS_ID=1578 — `median=0.000`, але насправді у 47% ринків substitution є на 73%
обсягу). Перехід:

| Старе поле | Замінено на |
|------------|-------------|
| `MEDIAN_SHARE_INTERNAL` | `MEAN_SHARE_INTERNAL` (= COEF_1 у Phase C) |
| — | `COVERAGE_PCT` = частка ринків з SHARE_INTERNAL > 0 |
| — | `CONDITIONAL_RETENTION` = mean(SHARE | SHARE > 0) |
| — | `MARKETS_WITH_SUB` = count of markets with SHARE > 0 |

**Декомпозиційний інваріант:** `MEAN_SHARE_INTERNAL = COVERAGE_PCT × CONDITIONAL_RETENTION`

Дозволяє розрізнити два сценарії з однаковим COEF_1:
- COVERAGE=1.0, CONDITIONAL=0.5 — у всіх ринках стабільно утримуємо 50%.
- COVERAGE=0.5, CONDITIONAL=1.0 — у половині ринків клієнт іде, у половині — повне утримання.

#### v2.1 — RELIABILITY metrics (Step 15, 2026-05-01)

Додано 4 нові поля для оцінки **статистичної надійності** COEF_1 — щоб аналітик міг
сортувати/фільтрувати препарати за рівнем достовірності розрахунку.

**Поля у `drug_statistics.parquet` (внутрішні діагностичні):**

| Поле | Тип | Формула / Значення |
|------|-----|---------------------|
| `STD_SHARE_INTERNAL` | float | std розкид SHARE_INTERNAL по ринках (після IQR), ddof=1 |
| `VARIATION_COEF` | float | CV = STD/MEAN; з guard rails для MEAN ≈ 0 |
| `RELIABILITY_LABEL` | str | HIGH (CV<0.15) / MEDIUM (0.15≤CV<0.30) / LOW (CV≥0.30) / SINGLE_MARKET (n<2) |
| `RELIABILITY_SCORE` | float ∈ [0,1] | composite — переходить у фінал |

**Поле у `drug_coefficients.csv` (фінал, 13-та колонка):**
- `RELIABILITY_SCORE` (float ∈ [0,1]) — composite показник для замовника.

#### Формула RELIABILITY_SCORE

```
RELIABILITY_SCORE = stability × sample_factor × modality_penalty   ∈ [0, 1]

де:
  stability         = clip(1 - CV, 0, 1)            якщо MEAN > 0
                    = 1.0                             якщо MEAN=0 і STD=0  (стабільно нуль)
                    = 0.0                             якщо STD > MEAN       (розкид > середнього)
  sample_factor     = min(1, log10(MARKET_COUNT_CLEAN) / log10(150))
                    (1.0 при ≥150 ринків; ~0.6 при 25; ~0.3 при 5)
  modality_penalty  = 0.85 якщо DRUG_CLASS=MULTIMODAL, інакше 1.0

Edge case: MARKET_COUNT_CLEAN < 2 → SCORE=0.0
```

#### Параметри (константи у `pipeline/cross_market.py`)

| Константа | Значення | Призначення |
|-----------|----------|-------------|
| `RELIABILITY_HIGH_THRESHOLD` | 0.15 | CV-поріг для HIGH (canonical-style) |
| `RELIABILITY_MEDIUM_THRESHOLD` | 0.30 | CV-поріг для MEDIUM/LOW |
| `SAMPLE_SATURATION_MARKETS` | 150 | Кількість ринків при якій sample_factor=1.0 |
| `MULTIMODAL_PENALTY` | 0.85 | Знижка для бімодальних препаратів |

#### Інтерпретація шкали RELIABILITY_SCORE

- `≥0.85` — дуже надійний (стабільний на 150+ ринках, UNIMODAL)
- `0.6–0.85` — помірно надійний
- `0.3–0.6` — межовий, перевіряти декомпозицію (COVERAGE × CONDITIONAL)
- `<0.3` — низька надійність (великий розкид / мала вибірка / MULTIMODAL з шумом)
- `0.0` — або SINGLE_MARKET, або STD > MEAN

#### Ключові edge cases та design decisions

1. **Препарат з усіма SHARE=0 (mean=0, std=0):**
   Формально `RELIABILITY_SCORE = 1.0` (stability=1.0, бо стабільно нуль).
   **Це математично коректно, але обмежено корисно для бізнес-відбору top-N**, бо
   `COEF_1 = 0` робить препарат тривіально критичним без додаткової інформації.
   Для бізнес-фільтрації top "цікавих" препаратів рекомендується додатково
   фільтрувати за `COEF_1 > 0` або поєднувати RELIABILITY_SCORE з обсягом продажів
   у ad-hoc скриптах (`_optional_calculations/`).

2. **MULTIMODAL penalty (0.85):**
   Для бімодальних препаратів одне число COEF_1 менш репрезентативне (краще дивитись
   на COVERAGE_PCT × CONDITIONAL_RETENTION). Penalty 0.85 м'який — лише −15%, бо
   замовник може комбінувати з декомпозиційними метриками для повної картини.

3. **Sample-size нелінійність (log10):**
   Логарифмічна сатурація — після 150 ринків додаткові ринки дають мінімальний
   приріст надійності. 25 ринків ≈ 0.6 від максимуму. Це віддзеркалює статистичну
   реальність: похибка середнього зменшується як 1/√N.

4. **Inваріант валідації** `DC_RELIABILITY_IN_0_1` (16-й у `validation_report.txt`):
   `RELIABILITY_SCORE ∈ [0, 1]` для всіх рядків.

#### Відмінності від канонічного

- Канонічний має `RELIABILITY` категорію (HIGH/MEDIUM/LOW) — у нас вона збережена як
  `RELIABILITY_LABEL` у внутрішньому parquet.
- **Додатково — `RELIABILITY_SCORE` (0..1)** як одна сортувальна метрика у фінальному
  CSV. У канонічному цього немає.
- Канонічний без `MULTIMODAL_PENALTY` і `sample_factor` логарифмічної сатурації —
  у нас це composite розширення.

---

## PHASE C — Final Export

### Phase C: Final Export (C0 + C1 + C2 + C3 + C4 в одному модулі)

**Статус:** ✅ Implemented (2026-04-27)
**Реалізація:** [`pipeline/final_export.py`](./pipeline/final_export.py) (~480 рядків)
**Відповідає канонічному:** `03_final_output/01_drug_coefficients.py` + `02_substitute_shares.py`
**Версія алгоритму:** v1.0

#### Призначення
Сформувати **4 фінальних файли** для Power BI: 2 CSV + 2 XLSX + validation_report.txt.

#### Вхід / Вихід
- **Вхід:**
  - `data/intermediate/02_cross_market/drug_statistics.parquet` (Phase B)
  - `data/intermediate/01_per_market/{ID}/substitute_shares.parquet` (Phase A4, всі ринки)
- **Вихід (results/final/):**
  - `drug_coefficients.csv` (sep=';', utf-8-sig)
  - `drug_coefficients.xlsx`
  - `substitute_shares.csv`
  - `substitute_shares.xlsx`
  - `validation_report.txt`

#### Алгоритм (повний реалізований)

```python
def run_final_export(min_market_count=20):
    # Inputs
    df_drugs = pd.read_parquet(drug_statistics_path)
    df_subs_market = pd.concat([read_parquet(p) for p in glob('*/substitute_shares.parquet')])

    # C0: Filter drugs by MIN_MARKET_COUNT
    df_accepted = df_drugs[df_drugs['MARKET_COUNT_TOTAL'] >= min_market_count]
    accepted_ids = set(df_accepted['DRUGS_ID'])

    # C1: Build drug_coefficients
    df_drug_coef = build_drug_coefficients(df_accepted)
    save_csv_xlsx(df_drug_coef, 'drug_coefficients')

    # C2: Build substitute_shares (LIFT-weighted cross-market)
    df_sub_shares = build_substitute_shares(df_subs_market, accepted_ids)
    save_csv_xlsx(df_sub_shares, 'substitute_shares')

    # C4: Validate + write report
    validation = validate_outputs(df_drug_coef, df_sub_shares, min_market_count)
    write_validation_report(validation, ...)
```

#### Sub-algorithm: `build_drug_coefficients`

```python
def build_drug_coefficients(df_accepted):
    df = df_accepted.copy()
    df = df.rename(columns={
        'MEDIAN_SHARE_INTERNAL': 'COEF_1',
        'MARKET_COUNT_TOTAL':    'MARKET_COUNT',
    })
    df['UNIQUENESS_COEF'] = (1.0 - df['COEF_1']).round(6)
    return df[DRUG_COEF_COLUMNS].sort_values('COEF_1', ascending=False)
```

#### Sub-algorithm: `build_substitute_shares` (LIFT-weighted з дедублікацією)

```python
def build_substitute_shares(df_subs_market, accepted_drug_ids):
    df = df_subs_market[df_subs_market['STOCKOUT_DRUG_ID'].isin(accepted_drug_ids)]

    # 1. Per pair cross-market: SUM(TOTAL_LIFT)
    pair_agg = df.groupby(['STOCKOUT_DRUG_ID', 'SUBSTITUTE_DRUG_ID']).agg(
        AGG_TOTAL_LIFT=('TOTAL_LIFT', 'sum'),
        MARKETS_COUNT=('CLIENT_ID', 'nunique'),
        DRUGS_NAME=('STOCKOUT_DRUG_NAME', 'first'),
        SUBSTITUTE_DRUG_NAME=('SUBSTITUTE_DRUG_NAME', 'first'),
        SAME_NFC1=('SAME_NFC1', 'first'),
    )

    # 2. Per stockout drug cross-market: SUM(INTERNAL_LIFT_dedup)
    # CRITICAL: dedup per (CLIENT_ID, STOCKOUT_DRUG_ID) — INTERNAL_LIFT повторюється
    # для всіх substitute pairs одного drug в одному ринку!
    df_internal = df[['CLIENT_ID', 'STOCKOUT_DRUG_ID', 'INTERNAL_LIFT']]\
        .drop_duplicates(subset=['CLIENT_ID', 'STOCKOUT_DRUG_ID'])
    internal_cross = df_internal.groupby('STOCKOUT_DRUG_ID')['INTERNAL_LIFT'].sum()

    # 3. SUBSTITUTE_SHARE (decimal 0-1)
    pair_agg['SUBSTITUTE_SHARE'] = pair_agg['AGG_TOTAL_LIFT'] / internal_cross

    # 4. RANK
    pair_agg['SUBSTITUTE_RANK'] = pair_agg.groupby('STOCKOUT_DRUG_ID')['SUBSTITUTE_SHARE']\
        .rank(method='first', ascending=False).astype(int)

    return pair_agg.rename({'STOCKOUT_DRUG_ID': 'DRUGS_ID'})[SUB_SHARES_COLUMNS]
```

**Інваріант:** `SUM(SUBSTITUTE_SHARE per DRUGS_ID) = 1.0` гарантований математично через дедублікацію + LIFT-weighted.

#### Структура `drug_coefficients.csv` (9 колонок)

| Колонка | Тип | Mandatory | Опис |
|---------|-----|-----------|------|
| `DRUGS_ID` | int | ✅ | Morion ID |
| `DRUG_CLASS` | str | ✅ | UNIMODAL / MULTIMODAL |
| `COEF_1` | float | ✅ | Медіанний коефіцієнт субституції (0-1) |
| `UNIQUENESS_COEF` | float | ✅ | 1 - COEF_1 |
| `DRUGS_NAME` | str | optional | Людська назва |
| `INN_ID` | int | optional | ID INN |
| `INN_NAME` | str | optional | Назва INN |
| `NFC1_ID` | str | optional | Форма випуску |
| `MARKET_COUNT` | int | optional | На скільки ринках покрито |

**Sort:** COEF_1 DESC

#### Структура `substitute_shares.csv` (8 колонок)

| Колонка | Тип | Mandatory | Опис |
|---------|-----|-----------|------|
| `DRUGS_ID` | int | ✅ | Stockout drug ID |
| `SUBSTITUTE_DRUG_ID` | int | ✅ | ID замінника |
| `SUBSTITUTE_SHARE` | float | ✅ | Частка LIFT-зважена (0-1) |
| `DRUGS_NAME` | str | optional | Stockout drug name |
| `SUBSTITUTE_DRUG_NAME` | str | optional | Substitute name |
| `SAME_NFC1` | bool | optional | Чи та сама форма випуску |
| `SUBSTITUTE_RANK` | int | optional | Ранг (1 = top) |
| `MARKETS_COUNT` | int | optional | На скількох ринках спостерігалась пара |

**Sort:** DRUGS_ID, SUBSTITUTE_RANK ASC

#### Інваріанти (12 — всі перевірено на smoke-test)

**drug_coefficients (6):**
1. ✅ No NaN in COEF_1
2. ✅ COEF_1 ∈ [0, 1]
3. ✅ UNIQUENESS_COEF = 1 - COEF_1 (max diff: 0.0)
4. ✅ DRUG_CLASS ∈ {UNIMODAL, MULTIMODAL}
5. ✅ MARKET_COUNT >= min_market_count (threshold)
6. ✅ DRUGS_ID унікальні

**substitute_shares (6):**
7. ✅ No NaN in SUBSTITUTE_SHARE
8. ✅ SUBSTITUTE_SHARE ∈ [0, 1]
9. ✅ **SUM(SHARE per DRUGS_ID) ≈ 1.0** (max diff: 0.000015 на smoke-test)
10. ✅ FK constraint: усі DRUGS_ID із sub_shares є в drug_coef
11. ✅ No duplicate (DRUGS_ID, SUBSTITUTE_DRUG_ID) pairs
12. ✅ RANK starts at 1 для всіх drugs

#### Edge Cases
| Ситуація | Поведінка |
|----------|-----------|
| 0 drugs пройшли threshold | Empty drug_coefficients.csv; substitute_shares також empty |
| 1 substitute для drug | SHARE = 1.0, RANK = 1 |
| Drug у drug_stats але БЕЗ substitute_shares (no pairs) | Drug у drug_coef, але відсутній у substitute_shares (нормально) |
| MARKETS_COUNT = 0 | Не може бути після фільтра — drug мав ≥1 ринок |

#### Параметри

| Параметр | Default | Опис |
|----------|---------|------|
| `MIN_MARKET_COUNT` (CLI: --min-market-count) | 20 | Sequential Analyzer Study 02 |
| `SHARE_SUM_EPSILON` | 0.01 | Tolerance для SUM(SHARE)=1.0 інваріанту |

#### Продуктивність (smoke-test 2026-04-27 на 5 ринках з threshold=3)
- 5,120 drugs input → 2,077 accepted (40.6%)
- 38,259 substitute pairs cross-market
- 4 файли + validation_report.txt
- **4.84 секунди**

#### Відмінності від канонічного

| Аспект | Канонічний (Phase 3) | Наш (Phase C) |
|--------|----------------------|----------------|
| Файли | 2 окремих скрипти | 1 файл `final_export.py` |
| Output XLSX | Кольорове маркування HIGH/MEDIUM/LOW | Без маркування (per user request) |
| `coef_business_reports/`, `subst_business_reports/` | Окремі subdirs | Усе в `results/final/` |
| `MEDIAN_SUBSTITUTION_COEF` | Назва колонки | Перейменовано на `COEF_1` (per user TЗ) |
| `UNIQUENESS_COEF` | Відсутнє | **Додано** як `1 - COEF_1` |
| `DRUG_CLASS` UNIMODAL/MULTIMODAL | Відсутнє | **Додано** через Hartigan dip test |
| RELIABILITY (HIGH/MEDIUM/LOW) | У canonical Phase 2 | Відсутнє у наших файлах |
| filter_summary.csv, rejected_drugs.csv | Окремі файли | Метрики у return dict + validation_report |
| substitute_summary.csv | Окремий файл | Не потрібен (не в спеці замовника) |

---

## ПОСИЛАННЯ НА КАНОНІЧНИЙ ПРОЕКТ

При сумнівах щодо реалізації — звертатися до:

| Тема | Канонічний документ |
|------|---------------------|
| Pipeline overview Phase 1 | `cross_pharm_market_analysis/docs/01_did_processing/00_PIPELINE_PHASE_1.md` |
| Data aggregation deep | `cross_pharm_market_analysis/docs/01_did_processing/01_DATA_AGREGATION.md` |
| Stockout detection deep | `cross_pharm_market_analysis/docs/01_did_processing/02_STOCKOUT_DETECTION.md` |
| DiD analysis deep | `cross_pharm_market_analysis/docs/01_did_processing/03_DID_NFC_ANALYSIS.md` |
| Substitute analysis deep | `cross_pharm_market_analysis/docs/01_did_processing/04_SUBSTITUTE_SHARE_ANALYSIS.md` |
| Phase 2 statistical methodology | `cross_pharm_market_analysis/docs/02_substitution_coefficients/02_01_STATISTICAL_METHODOLOGY.md` |
| Business context | `cross_pharm_market_analysis/docs/00_ai_rules/01_BUSINESS_CONTEXT.md` |
| Known issues & gotchas | `cross_pharm_market_analysis/docs/00_ai_rules/02_KNOWN_ISSUES.md` |

---

## CHANGELOG

| Дата | Версія | Зміни |
|------|--------|-------|
| 2026-04-27 | 1.0 | Створено скелет з усіма Phase A/B/C кроками (статус ⏳ TBD); глосарій; інваріанти; посилання на канонічний |
| 2026-04-27 | 1.1 | Phase A0 → ✅ Implemented (детальна імплементація, edge cases, продуктивність) |
| 2026-04-27 | 1.2 | Phase A1 → ✅ Implemented (per_market.py, parquet output, 137 MB → 0.92 MB на 44s) |
| 2026-04-27 | 1.3 | Phase A2 → ✅ Implemented (core/stockout.py, 8581 events за 19s, 9 інваріантів пройшли) |
| 2026-04-27 | 1.4 | Phase A3 → ✅ Implemented (core/did.py + core/nfc.py + ISSUE-013 FIX, 5350 events + 28621 pairs за 65s, 12+9+1 інваріантів пройшли) |
| 2026-04-27 | 1.5 | Phase A4 → ✅ Implemented (per_market.py extension, 4873 pairs за 0.18s завдяки Q-A3.3 optimization, 11/11 invariants пройшли) |
| 2026-04-27 | 1.6 | Phase B → ✅ Implemented (cross_market.py: 5120 drugs за 1.74s, IQR + Hartigan dip test, 9/9 invariants) |
| 2026-04-27 | 1.7 | Phase C → ✅ Implemented (final_export.py: 4 файли + validation за 4.84s, 12/12 invariants, END-TO-END WORKING) |
| 2026-04-27 | 1.8 | Step 9 — Robustness/UX: corruption-aware resume (`core/io_utils.py:phase_output_valid`), Rich Live TUI (`pipeline/runner.py`), persistent file-logging (`logs/run_TIMESTAMP.log`), `run.bat` launcher. Smoke-test 3 ринки (resume з кешу): 10.4s wall, 12/12 invariants PASSED. |
| 2026-04-28 | 1.9 | Step 13 — COEF_1 з median на mean (валідно для MULTIMODAL bimodal-розподілів). Phase B: прибрано `MEDIAN_SHARE_INTERNAL`, додано `MEAN_SHARE_INTERNAL`, `COVERAGE_PCT`, `CONDITIONAL_RETENTION`, `MARKETS_WITH_SUB`. Phase C: 9 → 12 колонок у drug_coefficients (3 декомпозиційні між UNIQUENESS_COEF і DRUGS_NAME). Інваріант: COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION (tolerance 0.001). +3 нові інваріанти у validation. validation_report.txt → reports/. Sanity-check на 1578 (MULTIMODAL): COEF_1 0.000 → 0.341. |
| 2026-04-28 | 1.10 | Step 14 — NFC1 master registry (`data/master/nfc1_config.json`) з accumulating discovery: `pipeline/discover_markets.py` тепер додатково читає колонку `NFC Code (1)` з усіх raw CSV (variant b) і накопичено оновлює JSON. `core/nfc.py` повністю переписаний — `is_compatible()` працює через бізнес-правила з JSON; невідомі категорії → standalone + warning. ORAL_GROUP перерозбито: `ORAL_SOLID_RETARD` (тверді ↔ тверді ретард); рідкі — окремо (exact-match only). Standalone test: 12/12 PASSED. |
| 2026-05-01 | 1.11 | Step 15 — RELIABILITY_SCORE: композитний показник надійності COEF_1 ∈ [0,1]. Phase B (`pipeline/cross_market.py`): додано 4 нові поля у `drug_statistics.parquet` — `STD_SHARE_INTERNAL`, `VARIATION_COEF`, `RELIABILITY_LABEL` (HIGH/MEDIUM/LOW/SINGLE_MARKET, canonical-style з порогами CV<0.15 / 0.30), `RELIABILITY_SCORE` = stability × sample_factor × modality_penalty. Phase C: drug_coefficients.csv 12 → 13 колонок (RELIABILITY_SCORE в кінці). +1 інваріант DC_RELIABILITY_IN_0_1 (всього 16 PASSED). Sanity-check на контрольних препаратах: НУРОФЕН (стабільний, MC=185) → 0.92; ИНФЛЮЦИД (CV=0.01, MC=82) → 0.85; ДИКЛОКАИН (MULTIMODAL bimodal) → 0.00. |
| 2026-05-01 | 1.12 | Step 16 — Phantom substitutes filter (ISSUE-016, FIXED). Phase C (`pipeline/final_export.py::build_substitute_shares`): додано фільтр `SUBSTITUTE_SHARE > 0` між Steps 4 (compute SHARE) і 5 (assign RANK). Виключає пари, які формально потрапили у `substitute_pairs.parquet` (LIFT > 0 хоч раз), але після cross-market агрегації + `round(6)` отримали SHARE = 0.0. Pattern: «broad model, narrow export» — intermediate parquet зберігає повну видимість, фільтр діє тільки на фінальний експорт. Impact: 134 101 → 134 081 пара (-20 фантомів, ≈0.015%). Sum-to-1 invariant + 16 інваріантів — усі PASSED. |
