# LOGS — `drug_substitution_engine`

> **Версія:** 1.0
> **Призначення:** Хронологічний журнал виконаних робіт. Дозволяє відновити контекст після збоїв сесії або компактингу.
> **Формат:** записи у **зворотному хронологічному порядку** (нові — зверху).

---

## Інструкція ведення

### Принципи
- Фіксувати **процес роботи** (не плани і не майбутні наміри)
- Конкретні артефакти, рішення, командні рядки — у тілі запису
- Тимчасові плани — у [ROADMAP.md](./ROADMAP.md), методологія — у [ALGORITHMS.md](./ALGORITHMS.md)

### Шаблон запису

```markdown
## YYYY-MM-DD HH:MM — Назва кроку ✅/⚠️/🔄

### Контекст
- (Опційно) Що передувало, чому почали саме цей крок

### Виконано
- Конкретні дії
- Файли створені/змінені (з шляхами)
- Команди (якщо нетривіальні)

### Output
- Створені артефакти (з шляхами)
- Зафіксовані метрики (час, розмір)

### Рішення (якщо ухвалені)
- Що вирішили + чому

### Наступний крок
- Що робити далі

### Статус: ✅ ЗАВЕРШЕНО / ⚠️ В РОБОТІ / 🔄 ВЛОЖЕНО ЗМІНИ
```

---

## 2026-05-01 — Крок 16: Phantom substitutes filter (ISSUE-016) ✅

### Контекст
Під час підготовки ad-hoc файлу для аналітика
(`_optional_calculations/top_1k_reliability_sales_volume/`) виявлено, що у
вихідному substitute_shares файлі деякі рядки мають `SUBSTITUTE_SHARE = 0.000000`.
Користувач справедливо запитав: «який же це тоді субститут, якщо його частка
заміщення складає 0?»

Перевірка показала, що це не баг файлу від аналітика, а **властивість самого
продакшн-пайплайну**:
- У вхідному PowerBI-файлі: 16 з 85 503 рядків мали SHARE=0.
- У нашому продакшн `results/final/substitute_shares.csv`: **20 з 134 101**
  (≈0.015 %) мали SHARE=0.

### Корінь проблеми (ISSUE-016)

Phase C (`pipeline/final_export.py::build_substitute_shares`) виконує
LIFT-зважену агрегацію substitute pairs:
1. Якщо substitute мав `LIFT > 0` хоч в одному ринку — пара потрапляє в
   substitute_pairs.parquet (Phase A3).
2. Phase C нормалізує SUBSTITUTE_SHARE до 1.0 на цільовий препарат.
3. Якщо інші substitutes отримали більшу частку, а конкретний substitute
   зустрічався тільки в малому ринку — після агрегації + `round(6)` його
   частка стає рівно `0.000000`.

Тобто пара **формально** валідна (модель її бачила), але ефективна вага = 0
— для бізнес-користувача це **не substitute**.

### Узгоджені рішення
- **Виправлення в самому продакшн-пайплайні** (не ad-hoc fix), щоб усі
  майбутні розрахунки виходили чистими.
- **Pattern «broad model, narrow export»**: intermediate parquet зберігає
  повну видимість для debugging/audit; фільтр діє ТІЛЬКИ на фінальний
  експорт у `results/final/`.
- **Точка фільтрації**: між Steps 4 (compute SHARE) і 5 (assign RANK), щоб
  ranking почати з 1 для значущих substitutes.
- **Ad-hoc input оновлено**: `run_substitutes_subset.py` тепер бере
  `results/final/substitute_shares.csv` (наш чистий продакшн), а не файл
  від аналітика. Файл аналітика архівовано як `_legacy_*.xlsx`.

### Виконано

**1. `pipeline/final_export.py`:**
```python
# Step 4b: Видалення «фантомних» substitutes (SHARE = 0 після нормалізації)
n_before_phantom_filter = len(pair_agg)
pair_agg = pair_agg[pair_agg["SUBSTITUTE_SHARE"] > 0].copy()
n_phantom_removed = n_before_phantom_filter - len(pair_agg)
```

**2. Phase B+C re-run** (з кешу A1-A4): 37 секунд.

**3. `_optional_calculations/.../config.py`:**
- `INPUT_SUBSTITUTE_SHARES_XLSX` → `INPUT_SUBSTITUTE_SHARES`
- Шлях: `inputs/substitute_shares_power_bi.xlsx` → `results/final/substitute_shares.csv`.

**4. `run_substitutes_subset.py`:** додано підтримку CSV (за розширенням
файлу), sheet name fallback на `"Substitute Shares"` для CSV-входу.

**5. Архівовано `_legacy_substitute_shares_power_bi.xlsx`** у inputs.

### Результати

| Файл | До | Після | Δ |
|------|------|--------|----|
| `results/final/substitute_shares.csv` | 134 101 | **134 081** | -20 phantoms |
| 16 інваріантів | усі PASSED | усі PASSED | без змін |
| Sum-to-1 max diff | 0.000011 | 0.000011 | без змін |
| min SUBSTITUTE_SHARE | 0.0 | **0.0000010** | реальні substitutes |

| Ad-hoc вихідний | До | Після |
|-----------------|------|--------|
| `substitute_shares_power_bi_filtered.xlsx` | 22 736 пар (з 16 phantoms) | **22 730 пар (0 phantoms)** |

### Output (зміни)
- `pipeline/final_export.py` (UPDATED — phantom filter)
- `results/final/substitute_shares.csv/.xlsx` (REGENERATED — без phantoms)
- `_optional_calculations/.../config.py` (UPDATED — новий input path)
- `_optional_calculations/.../run_substitutes_subset.py` (UPDATED — csv/xlsx detect)
- `_optional_calculations/.../outputs/substitute_shares_power_bi_filtered.xlsx` (REGENERATED)
- `docs/_methods_issues.md` (UPDATED — ISSUE-016 + CHANGELOG v1.3)
- `docs/ALGORITHMS.md` (UPDATED — CHANGELOG v1.12)

### Не зачеплено
- Phase A кеш (всі parquet) — без змін, повна видимість збережена.
- `pipeline/cross_market.py` — без змін.
- COEF_1, RELIABILITY_SCORE, інші drug_coefficients метрики — без змін.

### Статус: ✅ ЗАВЕРШЕНО — продакшн-пайплайн більше не видає phantom substitutes.

---

## 2026-05-01 — Крок 15: RELIABILITY_SCORE — показник надійності COEF_1 ✅

### Контекст
Після успішного передання v2-результатів аналітику замовника (повний прогон
9h35m → 6h09m, 6 264 препарати, 16/16 інваріантів PASSED) виникла потреба
**відібрати топ-N препаратів** для глибшого аналізу замовником. Користувач
запропонував додати показник надійності розрахованого COEF_1 — щоб аналітик
міг сортувати та фільтрувати препарати за статистичною достовірністю.

### Узгоджені рішення
- **Підхід композитний** (Варіант C з обговорення): один скаляр
  `RELIABILITY_SCORE ∈ [0,1]`, що враховує 3 фактори:
  1. **Stability** (1 − CV) — нормований розкид по ринках.
  2. **Sample factor** — log10-сатурація на 150 ринках.
  3. **Modality penalty** — 0.85 для MULTIMODAL.
- **Діагностичні поля** (`STD_SHARE_INTERNAL`, `VARIATION_COEF`,
  `RELIABILITY_LABEL`) зберігаються у внутрішньому
  `data/intermediate/02_cross_market/drug_statistics.parquet`. У фінальний
  `drug_coefficients.csv` виводиться **лише** `RELIABILITY_SCORE` (12 → 13
  колонок), у кінці після `MARKET_COUNT` — для backward compat з
  Power BI v2-візуалізаціями.
- **Edge case:** препарати з усіма SHARE=0 (тривіально критичні) отримують
  математично коректний SCORE=1.0 (`mean=0, std=0` → stability=1.0). Це
  навмисний design — не ламати формулу під бізнес-сценарії; ad-hoc
  фільтрації виносяться у `_optional_calculations/`.

### Виконано

**1. `pipeline/cross_market.py`:**
- Додано константи: `RELIABILITY_HIGH_THRESHOLD=0.15`,
  `RELIABILITY_MEDIUM_THRESHOLD=0.30`, `SAMPLE_SATURATION_MARKETS=150`,
  `MULTIMODAL_PENALTY=0.85`.
- Нова функція `calculate_reliability(clean_shares, mean, drug_class)` →
  4 поля: STD, CV, LABEL, SCORE.
- `aggregate_cross_market()` виклик нової функції; `DRUG_STATISTICS_COLUMNS`
  розширено з 13 до 17 полів.

**2. `pipeline/final_export.py`:**
- `DRUG_COEF_COLUMNS` розширено з 12 до 13 (RELIABILITY_SCORE в кінці).
- Новий інваріант `DC_RELIABILITY_IN_0_1` у `validate_outputs()` (16-й).

**3. Перерахунок Phase B+C з кешу A1-A4** (без full re-run): 60 секунд.

### Результати на повному датасеті

```
Розподіл RELIABILITY_SCORE серед 6,264 препаратів:
  min=0.0000  max=1.0000  mean=0.5975  median=0.6502
  q25=0.4295  q75=0.8201

RELIABILITY_LABEL (drug_statistics.parquet):
  HIGH:           3 432  (38.2 %)
  MEDIUM:         1 506  (16.8 %)
  LOW:            3 509  (39.1 %)
  SINGLE_MARKET:    537  ( 6.0 %)

Validation:  16/16 PASSED (включно з новим DC_RELIABILITY_IN_0_1)
```

### Sanity-check на контрольних препаратах

| ID | DRUG | CLASS | STD | CV | LABEL | SCORE |
|----|------|-------|-----|-----|-------|-------|
| 1578 | ДИКЛОКАИН | MULTIMODAL | 0.43 | 1.25 | LOW | **0.000** |
| 11722 | ИНФЛЮЦИД | UNIMODAL | 0.01 | 0.01 | HIGH | **0.846** |
| 314746 | НУРОФЕН ДЛЯ ДЕТЕЙ | UNIMODAL | 0.07 | 0.08 | HIGH | **0.915** |
| 51881 | КОРНЕРЕГЕЛЬ | UNIMODAL | 0.07 | 1.24 | LOW | **0.000** |
| 317377 | АЛЛЕГРА 180 МГ | UNIMODAL | 0.19 | 0.41 | LOW | **0.585** |

Логічно: НУРОФЕН (стабільний, велика вибірка) — найвищий; ДИКЛОКАИН
(MULTIMODAL з великим розкидом) — нуль; КОРНЕРЕГЕЛЬ (CV>1) — нуль.

### Виявлений нюанс (не баг)

TOP-10 за RELIABILITY_SCORE склали препарати з `COEF_1=0.0000`,
`SCORE=1.0000` (стабільно унікальні препарати, всі SHARE=0). Математично
коректно, але обмежено корисно для бізнес-відбору top-N "цікавих"
препаратів. Тому ad-hoc фільтрація виноситься в окремий простір
(див. наступний абзац). Документовано у `data_dictionary.txt` секція
[13] (блок WARNING) і у `ALGORITHMS.md` секція "Ключові edge cases".

### Архітектурне рішення для ad-hoc фільтрації

Створюється папка `_optional_calculations/` для специфічних запитів
замовника, які НЕ мають змінювати продакшн-пайплайн. Перша задача:
`top_1k_reliability_sales_volume/` — подвійний фільтр (sales volume DESC
+ RELIABILITY_LABEL ∈ {HIGH, MEDIUM}). Реалізація — окремим скриптом,
без впливу на `pipeline/`, `core/`, `config/`.

### Output (зміни)
- `pipeline/cross_market.py` (UPDATED — функція `calculate_reliability`)
- `pipeline/final_export.py` (UPDATED — +1 колонка, +1 інваріант)
- `results/final/drug_coefficients.csv` (1.6 → 1.7 MB; 12 → 13 cols)
- `results/final/drug_coefficients.xlsx` (591 → 732 KB)
- `data/intermediate/02_cross_market/drug_statistics.parquet` (13 → 17 cols)
- `reports/validation_report.txt` (15 → 16 інваріантів)
- `reports/data_dictionary.txt` (UPDATED — нова секція [13])
- `docs/ALGORITHMS.md` (UPDATED — Phase B v2.1 блок + CHANGELOG v1.11)

### Не зачеплено
- substitute_shares.csv/.xlsx — без змін
- COEF_1, UNIQUENESS_COEF, COVERAGE_PCT, CONDITIONAL_RETENTION,
  MARKETS_WITH_SUB значення — БЕЗ змін
- Phase A кеш — без змін
- snapshot `_comparison/` — без змін

### Статус: ✅ ЗАВЕРШЕНО — RELIABILITY_SCORE є частиною методології v2.1.

---

## 2026-04-28 — Крок 14: Динамічний NFC1-registry + перерозбиття ORAL_GROUP ✅

### Контекст
На презентації керівництву виявлено 2 методологічні проблеми у частині NFC1:
1. **Hardcoded NFC1-список** у `core/nfc.py` був скопійований 1-в-1 з канонічного проекту. Канонічний список покривав лише ті форми випуску, які зустрічалися у канонічному датасеті — для нашого датасету (і всіх майбутніх) це принципово неповно. Якщо приходить нова категорія, якої не було в канонічному — pipeline її ігнорує без жодного сигналу.
2. **Помилка у бізнес-логіці ORAL_GROUP**: рідкі пероральні форми (сиропи, розчини) у канонічному вважалися взаємозамінними з твердими таблетками. Але клінічно це різні клієнтські сценарії — клієнт, що бере сироп, з малою імовірністю погодиться на таблетки.

### Узгоджені рішення
- **NFC1 — динамічний accumulating master registry**:
  - `data/master/nfc1_config.json` — single source of truth.
  - При кожному discovery scan-ять усі raw CSV → нові категорії додаються накопичувано (старі лишаються як історичні).
  - `compatibility_groups` і `excluded` — бізнес-правила, ніколи не перезаписуються автоматично.
  - Невідома категорія (вперше зустрінута, не в registry) → standalone (exact-match only) + warning у лог.
- **Перерозбиття ORAL_GROUP**:
  - Стара група: тверді обычные ↔ рідкі обычные ↔ тверді ретард.
  - Нова група `ORAL_SOLID_RETARD`: тільки тверді обычные ↔ тверді ретард.
  - Рідкі (`Пероральные жидкие обычные`) тепер замінюються тільки самі на себе.

### Виконано

**1. Backup кешу Phase A** (~2 хв):
`data/intermediate/01_per_market_backup_2026-04-28/` (2.3 GB, 1025 файлів) — на випадок rollback.

**2. `config/paths.py`:**
- Додано `MASTER_PATH = DATA_PATH / "master"` + `NFC1_CONFIG_PATH = MASTER_PATH / "nfc1_config.json"`.
- Оновлено `ensure_directories()` (додано MASTER_PATH).

**3. `pipeline/discover_markets.py`:**
- Додано `scan_nfc1_in_file()` — читає лише колонку `NFC Code (1)` з повного raw CSV (variant b).
- Додано `update_nfc1_config()` — accumulating update master JSON (immutable `first_discovered_at`, оновлювана `last_discovered_at`).
- `discover_markets()` повертає тепер 3 значення: df, summary, discovered_nfc1.
- `main()` оновлює master JSON і виводить newly-added категорії.
- Default `compatibility_groups` = `[ORAL_SOLID_RETARD]`; default `excluded` = `["Не предназначенные для использования у человека и прочие"]`.

**4. `core/nfc.py` (повний rewrite, v2):**
- Прибрано hardcoded `ORAL_GROUP`, `EXCLUDE_FORMS`, `ALL_NFC1_CATEGORIES`.
- Додано `NFCConfig` (lazy-loaded singleton): читає JSON, кешує `groups_by_form` для O(1) lookup.
- `is_compatible(a, b)` тепер працює через групи з конфігу. Невідома категорія → warning у лог (один раз на форму) + exact-match-only.
- `get_compatibility_group(form)` повертає назву групи / `EXACT_MATCH` / `EXCLUDED`.
- Self-test читає реальний JSON.

**5. Bootstrap `nfc1_config.json`** (з Phase A1 кешу):
16 NFC1-категорій з поточного датасету (the pharmacy chain). Файл 3.1 KB.

**6. Snapshot `results/_comparison/before_v2_2026-04-28/`** (63 MB):
- 4 Power BI файли (median-based, з ORAL_GROUP v1).
- `reports_snapshot/`: validation_report + business_report.
- `README.txt` з контекстом.

### Standalone test (12/12 PASSED)

```
Tablets + Tablets             = True   (exact match)
Tablets + Retard tablets      = True   (одна група ORAL_SOLID_RETARD)
Tablets + Liquid              = False  ← ЗМІНА (раніше True)
Retard tablets + Liquid       = False  ← ЗМІНА
Liquid + Liquid               = True   (exact match)
Parenteral + Parenteral       = True
Parenteral + Ophthalmic       = False
Tablets + Excluded            = False
Unknown category + same       = True   (exact match)
Unknown category + Tablets    = False  + warning у лог
```

### Output (зміни)
- `core/nfc.py` (FULL REWRITE — динамічна логіка)
- `pipeline/discover_markets.py` (UPDATED — +NFC1 discovery)
- `config/paths.py` (UPDATED — +MASTER_PATH)
- `data/master/nfc1_config.json` (NEW, 3.1 KB)
- `data/intermediate/01_per_market_backup_2026-04-28/` (NEW backup, 2.3 GB)
- `results/_comparison/before_v2_2026-04-28/` (NEW snapshot, 63 MB)

### Що НЕ зроблено цим кроком (заплановано наступне)
- **Повний discover_markets із raw CSV** (~5-10 хв) — підтвердити що `scan_nfc1_in_file` працює на повному датасеті, оновить timestamp у JSON.
- **Видалення `did_events.parquet` + `substitute_pairs.parquet` + `substitute_shares.parquet`** з усіх 205 теч — щоб resume-логіка перерахувала Phase A3 + A4 з новою NFC compatibility.
- **Повний перезапуск pipeline** (~5 годин): Phase A1+A2 з кешу, A3+A4 наново, B+C наново (з оновленою mean-логікою з Кроку 13).
- **Перерахунок `business_report.txt`** після прогону.

### Статус: ✅ Код готовий, тести PASSED. Очікує запуску повного перерахунку.

---

## 2026-04-28 — Крок 13: Перехід COEF_1 з median на mean + декомпозиційні метрики ✅

### Контекст
Користувач знайшов методологічну проблему на прикладі препарату **DRUGS_ID=1578** (ДИКЛОКАИН, MULTIMODAL): `COEF_1=0.000` за поточним методом (median), але у `substitute_shares` для цього препарату є substitutes з реальними частками (ОЛФЕН-75 на 99.7%). Виявилось — для MULTIMODAL препаратів медіана приховує бімодальність розподілу і дає невалідну для бізнесу цифру.

Узгоджено: переходимо на **mean** (Варіант B+C з обговорення) і додаємо 3 декомпозиційні метрики, які математично розкладають COEF_1 на компоненти.

### Узгоджені рішення
- **COEF_1**: `median(SHARE_INTERNAL after IQR)` → `mean(SHARE_INTERNAL after IQR)`. Тепер єдина формула для UNIMODAL і MULTIMODAL.
- **Прибираємо `MEDIAN_SHARE_INTERNAL`** з `drug_statistics.parquet` як зайву проміжну метрику.
- **Додаємо 3 нові колонки** в `drug_coefficients.csv` (Варіант 1 — між UNIQUENESS_COEF і DRUGS_NAME):
  - `COVERAGE_PCT` — частка ринків з SHARE > 0
  - `CONDITIONAL_RETENTION` — mean(SHARE | SHARE > 0)
  - `MARKETS_WITH_SUB` — абсолютна кількість таких ринків
- **Інваріант декомпозиції**: `COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION` (валідується автоматично, tolerance 0.001).
- **Validation_report.txt** тепер пишеться в `reports/`, а не в `results/final/` (синхронізація з новою структурою папок: `reports/` для звітів, `docs/` для документації).
- **Без повного прогону** — лише standalone in-memory test на існуючому кеші, фінальні файли не перезаписуються (бо буде ще одна модифікація по NFC1).

### Виконано

**1. `pipeline/cross_market.py`:**
- Прибрано `MEDIAN_SHARE_INTERNAL` з `DRUG_STATISTICS_COLUMNS`.
- Додано 4 нових поля: `MEAN_SHARE_INTERNAL`, `COVERAGE_PCT`, `CONDITIONAL_RETENTION`, `MARKETS_WITH_SUB`.
- Функція `aggregate_cross_market()` тепер обчислює всі 4 метрики на per-market SHARE_INTERNAL після IQR Тукі 1.5×.

**2. `config/paths.py`:**
- Додано `REPORTS_PATH = PROJECT_ROOT / "reports"`.
- Додано в `ensure_directories()`.

**3. `pipeline/final_export.py`:**
- `DRUG_COEF_COLUMNS` розширено з 9 до 12 колонок (Варіант 1: позиції 5-7).
- Джерело `COEF_1` змінено з `MEDIAN_SHARE_INTERNAL` на `MEAN_SHARE_INTERNAL`.
- Додано 3 нові інваріанти у `validate_outputs()`: `DC_COVERAGE_IN_0_1`, `DC_CONDITIONAL_IN_0_1`, `DC_DECOMPOSE_FORMULA`.
- `validation_report.txt` тепер пишеться у `REPORTS_PATH`.
- Додано константу `DECOMPOSE_EPSILON = 0.001`.

**4. Standalone test (`_test_new_metrics.py`):**
Новий скрипт ганяє оновлений Phase B+C in-memory на існуючому кеші 205 ринків, перевіряє 3 контрольні препарати + декомпозицію на 100 випадкових. **Результати PASSED** — фінальні файли не перезаписувались.

**5. `reports/data_dictionary.txt`:**
- 3 нові секції: `[5] COVERAGE_PCT`, `[6] CONDITIONAL_RETENTION`, `[7] MARKETS_WITH_SUB`.
- Оновлено `[3] COEF_1` (нова формула + WARNING-блок про MULTIMODAL).
- Оновлено `[2] DRUG_CLASS` (посилання на нові декомпозиційні метрики).
- Перенумеровано решту секцій (8-12) і посилання у substitute_shares.

### Sanity-check на 3 контрольних препаратах (in-memory)

| DRUGS_ID | Назва | DRUG_CLASS | COEF_1 (новий) | COVERAGE | CONDITIONAL | MARKETS_WITH_SUB |
|----------|-------|-----------|----------------|----------|-------------|-------------------|
| **1578** | ДИКЛОКАИН | MULTIMODAL | **0.341** (раніше 0.000) | 0.467 | 0.731 | 14 / 30 |
| **314746** | НУРОФЕН ДЛЯ ДЕТЕЙ | UNIMODAL | **0.975** (раніше 0.978) | 1.000 | 0.975 | 175 / 185 |
| **51881** | КОРНЕРЕГЕЛЬ | UNIMODAL | **0.059** (раніше 0.025) | 0.539 | 0.110 | 104 / 199 |

Декомпозиційний інваріант на 100 випадкових препаратах: max diff = 0.0000011 << 0.001 ✓

**Цікавий висновок**: для UNIMODAL зі скошеним розподілом (як КОРНЕРЕГЕЛЬ) mean кардинально точніший за median (0.059 vs 0.025) — у 54% ринків substitution є на низькому рівні (~11%), що median ігнорує.

### Output (зміни)
- `pipeline/cross_market.py` (UPDATED)
- `pipeline/final_export.py` (UPDATED)
- `config/paths.py` (UPDATED)
- `reports/data_dictionary.txt` (UPDATED)
- `_test_new_metrics.py` (NEW — standalone test, можна видалити після фінального прогону)

### Не зачеплено
- Phase A (per-market) — кеш did_events.parquet валідний.
- substitute_shares.csv/.xlsx — структура без змін.
- DRUG_CLASS (Hartigan dip test) — без змін.
- Фінальні файли в `results/final/` — без змін (старі цифри з median).
- `business_report.txt` — буде перерахований після наступного повного прогону.

### Статус: ✅ ЗАВЕРШЕНО — нова логіка перевірена in-memory, готова до повного прогону після наступної модифікації (NFC1 — за окремим узгодженням).

---

## 2026-04-27 — Крок 12: Реструктуризація проекту і ребрендинг ✅

### Контекст
Після завершення обчислювального циклу і написання бізнес-звіту користувач створив нову папку `D:\RADYSLAV_PROJECTS\PROJECTS\` для зберігання робочих проектів. Поставив 4 задачі:
1. Перемістити проект у `PROJECTS\`.
2. Перейменувати venv `lib_env` → `_lib_env` і теж перемістити в `PROJECTS\`.
3. Перейменувати проект на більш загальну назву (тепер це шаблон-модуль для будь-якого замовника, не лише для the pharmacy chain).
4. Усі hardcoded шляхи й назви — оновити.

### Узгоджені рішення
- **Нова назва проекту**: `drug_substitution_engine` (англомовно, "engine" = шаблон-двигун).
- **Venv**: видалити старий і створити новий з `requirements.txt` (Опція Б — надійніше за `mv`, який міг би зламати `Activate.ps1`/`pip` shim).

### Виконано

**1. Новий venv (з нуля):**
- Створено `D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\` через глобальний Python 3.13.1.
- Встановлено всі пакети з `requirements.txt`: pandas 2.3.3, pyarrow 24.0.0, scipy 1.17.1, diptest 0.11.0, rich 15.0.0, openpyxl 3.1.5, xlsxwriter 3.2.9, tqdm 4.67.3, numpy 2.4.4 + транзитивні.
- Sanity-test imports — усі OK.
- Видалено старий `D:\RADYSLAV_PROJECTS\lib_env\` (382 MB).

**2. Переміщення проекту:**
- `mv` через bash і `Move-Item` через PowerShell не спрацювали (Permission denied — VSCode/Claude Code тримав directory handle).
- Спрацював **Robocopy /MOVE /E** — він копіює файл-за-файлом і видаляє джерело, обходячи лок директорного хендла.
- Результат: `D:\RADYSLAV_PROJECTS\previous_project_alias\` → `D:\RADYSLAV_PROJECTS\PROJECTS\drug_substitution_engine\` (2.4 GB, всі підпапки).

**3. Оновлення critical шляхів:**
- `run.bat` — `PYTHON_EXE` оновлено на новий шлях venv; назва pipeline у заголовках змінена.
- `requirements.txt` — оновлено коментар з шляхом venv.
- `config/paths.py` — оновлено header docstring і self-test print.
- 25 згадок `previous_project_alias` у `.py` коментарях замінено на `drug_substitution_engine` через одну sed-команду.

**4. Оновлення документації (.md):**
- 13 згадок `previous_project_alias` замінено в ALGORITHMS.md, LOGS.md, ROADMAP.md, _methods_issues.md (заголовки + структури папок + посилання).
- Абсолютні шляхи оновлено: `D:\RADYSLAV_PROJECTS\previous_project_alias\` → `D:\RADYSLAV_PROJECTS\PROJECTS\drug_substitution_engine\`, `D:\RADYSLAV_PROJECTS\lib_env\` → `D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\`.
- README.md залишається на доопрацювання у наступному кроці (Етап 3 — підготовка до GitHub).

**5. Незмінні шляхи (свідомо):**
- `RAW_DATA_PATH = D:\RADYSLAV_PROJECTS\DATA_SETS\pd_ds_4_pres` — папка з даними замовника **не переміщувалась**, шлях у `config/paths.py` лишається.
- Внутрішні шляхи проекту (`data/`, `results/`, `logs/`) обчислюються через `Path(__file__).resolve().parent.parent` → автоматично адаптувались до нового розташування.

### Smoke-test після реструктуризації
```
D:\...\PROJECTS\_lib_env\Scripts\python.exe -m pipeline.full_run
```
- Phase A: 205 ринків з кешу (skip — 0s).
- Phase B + Phase C: повний перерахунок з MIN_MARKET_COUNT=20.
- 6 265 препаратів, 182 164 substitute pairs, **12/12 invariants PASSED**.
- Wall time: **47.9 s**, ідентично попередньому стану.
- Лог пишеться у `D:\RADYSLAV_PROJECTS\PROJECTS\drug_substitution_engine\logs\`.

### Структура після реструктуризації
```
D:\RADYSLAV_PROJECTS\
├── DATA_SETS\pd_ds_4_pres\         ← raw CSV (read-only, незмінні)
├── PROJECTS\
│   ├── _lib_env\                   ← НОВИЙ ізольований venv
│   └── drug_substitution_engine\   ← переміщений проект (2.4 GB)
└── cross_pharm_market_analysis\    ← канонічний референс (незмінний)
```

### Output
- `D:\RADYSLAV_PROJECTS\PROJECTS\_lib_env\` (NEW, 380+ MB)
- `D:\RADYSLAV_PROJECTS\PROJECTS\drug_substitution_engine\` (MOVED)
- `run.bat`, `requirements.txt`, `config/paths.py` (UPDATED — critical paths)
- 25 .py файлів (UPDATED — header comments) + 4 .md файли (UPDATED — назва і шляхи)
- Видалено: `D:\RADYSLAV_PROJECTS\lib_env\` (старий venv), `D:\RADYSLAV_PROJECTS\previous_project_alias\` (стара локація проекту).

### Статус: ✅ ЗАВЕРШЕНО — проект як шаблонний обчислювальний модуль готовий до підготовки під GitHub-портфоліо.

---

## 2026-04-27 — Крок 11: Cosmetic UI fixes у runner.py ✅

### Контекст
Під час повного прогону (9h 35m, 205 ринків) користувач помітив два UI-дефекти у Rich Live dashboard:
1. **«200 активних workers»** — в панелі Active workers відображалися всі submited futures з однаковим стартовим часом, замість лише 6 реально-running.
2. **ETA `0:00:01`** — Rich `TimeRemainingColumn` плутався через перші 3 ринки з кешу (resume за мс), що дало завищену середню швидкість.

Фікси відкладені до завершення повного прогону, щоб не переривати 9-годинні розрахунки.

### Виконано

**1. `pipeline/runner.py:_make_banner()` — кастомний ETA:**
- Додано параметри `completed`, `total`, `overall_t0`.
- ETA розраховується як `(elapsed_wall_time / completed) × remaining` після ≥5 завершених ринків.
- На малій вибірці (< 5 завершень) показує `ETA: calculating... (X/Y done — need 5+ for stable estimate)`.
- Виводить не лише тривалість, а й абсолютний час `(≈ finish at HH:MM:SS)`.

**2. `pipeline/runner.py:run_parallel()` — fix active_markets:**
- Прибрано `active_markets[t[0]] = time.time()` зі циклу `executor.submit(...)`.
- У polling loop додано детекцію реально-running futures через `f.running()`:
  ```python
  for f in pending:
      cid = future_to_cid[f]
      if f.running() and cid not in active_markets:
          active_markets[cid] = now_ts
  ```
- Тепер у панелі Active workers показуються лише реально-зайняті workers (≤ max_workers), а не всі submited.

**3. Cleanup Progress bar:**
- Прибрано `TimeRemainingColumn` з імпорту і Progress (його замінив кастомний ETA в banner).

### Жива перевірка
```
python -m pipeline.runner --market-ids 763807 1439971 --force --workers 2
```
- Wall time: **3m 11s** (sequential equiv 5m 21s, speedup 1.68×).
- Active workers panel: коректно показав 2 з 2 під час роботи, "All workers idle" у фінальі.
- ETA banner: `calculating... (2/2 done — need 5+ for stable estimate)` (нормальна поведінка для малої вибірки).
- 2/2 success, 0 errors, all phases executed (force=True).

### Output
- `pipeline/runner.py` (UPDATED): `_make_banner()`, `run_parallel()` polling loop, imports.

### Статус: ✅ ЗАВЕРШЕНО — pipeline UI готовий до наступних повних прогонів з адекватним ETA та коректною панеллю активних workers.

---

## 2026-04-27 — Крок 10: Бізнес-звіт по результатах ✅

### Контекст
Після успішного завершення повного прогону (6,265 препаратів, 182,164 substitute pairs, 12/12 invariants PASSED) користувач запросив написати бізнес-звіт для аналітика+замовника.

### Виконано
- Глибокий аналіз результатів: розподіл COEF_1, сегментація A/B/C, концентрація заміни, top NFC1.
- Відбір 3 препаратів-прикладів за принципом «один з кожного сегмента»:
  - HIGH (COEF_1=0.978): НУРОФЕН ДЛЯ ДЕТЕЙ — 96 substitutes, заміна сильно розосереджена.
  - MID (COEF_1=0.484): АЛЛЕГРА 180 МГ — 6 substitutes, top-1 ТИГОФАСТ-180 покриває 46%.
  - LOW (COEF_1=0.025): КОРНЕРЕГЕЛЬ — 1 substitute (СІКАПРОТЕКТ), 97.5% обсягу йде з мережі при stockout.
- Написано звіт `results/final/business_report.txt` (UTF-8, ~2,130 слів, 408 рядків, 27 KB).

### Структура звіту (9 секцій)
1. Резюме для керівництва (10 рядків)
2. Що рахували і чому (бізнес-питання + спрощена методологія)
3. Ключові цифри (вхідні дані, розподіли, концентрація заміни)
4. Бізнес-сегментація A/B/C (Безпечні / Помірні / Критичні)
5. 3 конкретні приклади з реальними substitutes
6. Рекомендації для мережі (tier-based stocking, ревізія 370 SKU без subs)
7. Технічні нотатки (DiD з ISSUE-013 fix, 9.5h обробки)
8. Обмеження (SHARE_INTERNAL = обсяг ≠ клієнти; INN=0 для гомеопатії)
9. Файли для Power BI (схема + ідеї візуалізацій)

### Output
- `results/final/business_report.txt` (NEW, 27 KB).

### Статус: ✅ ЗАВЕРШЕНО — звіт готовий для аналітика і замовника.

---

## 2026-04-27 — Крок 9: TUI + Persistent Logging + Resume + Launcher ✅

### Контекст
Перед фінальним прогоном на всіх ~205 ринках (8–10 год) користувач обрав **Опцію 2** — узгодити фінальні штрихи last-mile інфраструктури:
1. Rich Live TUI dashboard для phase A runner.
2. Persistent file-logging кожного запуску у `logs/run_TIMESTAMP.log`.
3. Corruption-aware resume (детектує і прибирає биті parquet).
4. Windows `.bat` launcher (подвійний клік).

### Виконано

**1. `core/io_utils.py`** (NEW, ~70 рядків):
- `is_valid_parquet(path)` — `pq.read_metadata()` як швидкий sanity-check.
- `phase_output_valid(path, auto_delete_corrupt=True)` — повертає `True`, якщо parquet валідний; інакше **видаляє** биті файли, щоб не блокувати resume.

**2. `pipeline/per_market.py`** — оновлено `process_market_full()` так, що skip-логіка кожної фази (A1/A2/A3/A4) використовує `phase_output_valid()` замість простого `path.exists()`. Якщо парqquet був написаний частково (kill під час write), наступний запуск його прибере й перерахує.

**3. `pipeline/runner.py`** (refactor, ~370 рядків):
- Rich `Live` dashboard з `RenderableGroup`: banner → progress bar → active workers panel → stats table.
- Polling loop: `concurrent.futures.wait(..., timeout=1.0, return_when=FIRST_COMPLETED)` для тікаючого UI.
- На завершення — фінальна статистика (`Wall time`, `Sequential equivalent`, `Speedup`, executed/skipped per phase).
- Аліас runtime: `_make_banner`, `_make_active_table`, `_make_stats_table`, `_format_time`.

**4. `pipeline/full_run.py`** (~480 рядків):
- Pre-flight (DATA_SETS path/disk space/markets_list).
- `setup_persistent_logging()` — `RotatingFileHandler` у `logs/run_YYYYMMDD_HHMMSS.log`, all module-loggers attach.
- Orchestrator: discover → A → B → C → final summary.
- CLI: `--limit N`, `--workers N`, `--force`, `--min-market-count N`.
- Final summary: дві Rich-таблиці (Pipeline status, Output files) + Started/Finished/Wall time/Log file.

**5. `run.bat`** (NEW, 63 рядки) — Windows launcher:
- `cd /d "%~dp0"` (працює з будь-якого подвійного кліку).
- Жорстко вказує `D:\RADYSLAV_PROJECTS\lib_env\Scripts\python.exe` (ізольований venv).
- Передає `%*` у `python -m pipeline.full_run`.
- `pause` наприкінці, щоб вікно не закривалось.

**6. `README.md`** (REWRITE) — швидкий старт, опис фаз, аргументів CLI, resume, логи.

### Smoke-test (3 ринки, після Step 9)
```
run.bat --limit 3 --min-market-count 3
```
- Phase A: 3/3 success (resume з кешу — wall time 1s, 12 phase-skips).
- Phase B: 5,995 unique drugs (5,932 UNIMODAL + 63 MULTIMODAL), 200,652 DiD events, 2.10s.
- Phase C: 2,965 drugs accepted, 61,823 substitute pairs, **усі 12 інваріантів PASSED**, 7.46s.
- Output: `drug_coefficients.csv` (752 KB), `.xlsx` (270 KB), `substitute_shares.csv` (16.8 MB), `.xlsx` (3.7 MB), `validation_report.txt` (1.15 KB).
- **Total wall time: 10.4s** (повністю з кешу).

### Виявлені проблеми та фікси
- **UnicodeEncodeError на Windows cp1251**: emoji `🏁`, `📁`, `⚠️` у print/Table title → видалено (Windows console pipe не вміє encode-ити emoji за межами BMP). Файли: `pipeline/full_run.py:300, 304`, `pipeline/per_market.py:645`.
- **PowerShell `Select-Object -Last 60` буферизує** stdout до завершення процесу — не використовуємо для long-running commands.

### Output
- `core/io_utils.py` (NEW)
- `pipeline/runner.py`, `pipeline/full_run.py`, `pipeline/per_market.py` (UPDATED)
- `run.bat` (NEW)
- `README.md` (REWRITE)
- `logs/run_20260427_094847.log` — перший повний прогон з persistent log.

### Статус: ✅ ЗАВЕРШЕНО — pipeline готовий до повного прогону на всіх ринках.

---

## 2026-04-27 — Крок 1: Skeleton + Phase A0 Discovery ✅

### Контекст
Реалізація Кроку 1 згідно ROADMAP §9. Перед написанням коду провели детальний line-by-line огляд канонічного `01_preproc.py` (277 рядків), узгодили 5 блоків модифікацій (Q-B1...Q-B5).

### Узгоджені рішення (line-by-line review)
- **Q-B1**: переміщення `parse_period_id` у `core/etl.py` одразу
- **Q-B2**: утиліти `format_date`, `calculate_weeks` лишаємо локально
- **Q-B3**: **Опція 2** — sniff-only (`nrows=3`) у discovery, повна статистика поетапно у Phase A1
- **3.1-3.9**: усі модифікації `process_single_file` (валідація колонок, STATUS, try/except, прибрати print)
- **Q-B4**: `STATUS` в одному файлі, без окремого `malformed_files.csv`
- **4.1-4.6**: 3 виходи замість 6, перейменування на `markets_list.csv`
- **Q-B5**: `--limit N` для smoke-test

### Виконано

**1. Skeleton:**
```
drug_substitution_engine/
├── config/
│   ├── __init__.py
│   ├── paths.py            (NEW, 156 рядків)
│   ├── machine_params.py   (NEW, 144 рядки)
│   └── column_mapping.py   (NEW, 159 рядків — копія канонічного, спрощена)
├── core/
│   ├── __init__.py
│   └── etl.py              (NEW, 117 рядків — parse_period_id*, align_to_monday)
├── pipeline/
│   ├── __init__.py
│   └── discover_markets.py (NEW, 250 рядків)
├── data/intermediate/00_preproc/
├── data/intermediate/01_per_market/
├── results/final/
└── logs/
```

**2. Self-tests кожного модуля:**
- `python -m config.paths` ✅ (валідація raw_data, ensure_directories)
- `python -m config.column_mapping` ✅ (validate_raw_columns OK для повного/часткового набору)
- `python -m config.machine_params` ✅ (8 cores, 32 GB, 6 workers, 1 thread, HDD)
- `python -m core.etl` ✅ (parse_period_id для 4 тестових PERIOD_ID)

**3. Smoke-test discover_markets на 5 файлах:**
```
python -m pipeline.discover_markets --limit 5
```
Результат:
- Total: 5
- READY: 5
- EMPTY: 0
- MALFORMED: 0
- Elapsed: **0.10 sec** (sniff-only стратегія підтверджена як швидка)

**4. Згенерований артефакт `markets_list.csv`:**
```csv
CLIENT_ID;FILE_NAME;FILE_PATH;FILE_SIZE_MB;STATUS;REASON
103097;103097.csv;D:\...\103097.csv;255.01;READY;
103103;103103.csv;D:\...\103103.csv;520.85;READY;
104266;104266.csv;D:\...\104266.csv;653.15;READY;
107221;107221.csv;D:\...\107221.csv;945.69;READY;
109317;109317.csv;D:\...\109317.csv;514.97;READY;
```

### Output
```
data/intermediate/00_preproc/
└── markets_list.csv   (5 рядків, 6 колонок, sep=';', encoding=utf-8-sig)
```

### Метрики (екстраполяція)
- Sniff 5 файлів за 0.10 сек → 207 файлів за **~4 сек** (лінійно)
- Прогноз для повного запуску discovery на 207 файлах: ≤ 5 секунд

### Виявлені баги та fix
- **SyntaxWarning у config/paths.py docstring** через `\R` — виправлено через raw-string `r"""..."""`
- **Cyrillic в PowerShell консолі** показуються як `�` — це display-only, у CSV запис коректний (utf-8-sig)

### Технічні рішення (нюанси імплементації)
- `discover_markets.py` не використовує stdout `print()` — лише rich.print + rich.Table для красивого виводу
- `sniff_market_file()` повертає dict зі стандартизованим STATUS навіть при помилках (try/except охоплює all)
- Сортування markets_list: READY → EMPTY → MALFORMED, всередині по CLIENT_ID
- Exit code: 0 якщо ≥1 READY, 1 інакше

### Наступний крок
- Користувач підтверджує артефакт + (опційно) запуск повного discovery на 207 файлах
- Перехід до **Кроку 2: Phase A1 — Data Aggregation** (читання raw + gap filling + weekly aggregation)

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 3: Phase A2 — Stockout Detection ✅

### Контекст
Після узгодження Q-A2.1...Q-A2.7 та створення `_methods_issues.md` — реалізація Phase A2 з канонічною логікою 1-в-1.

### Виконано

**1. `core/stockout.py` (NEW, 215 рядків):**
- `identify_stockout_periods(df_drug, min_stockout_weeks)` — vectorized через diff()+cumsum()
- `validate_stockout_event(df_drug, df_inn, ...)` — 3-рівнева валідація 1-в-1 з канонічного
- Self-test PASSED: 2 stockout periods correctly identified, edge cases handled

**2. `pipeline/per_market.py` РОЗШИРЕНО:**
- Перебудовано CLI на subcommand argparse: `a1`, `a2`
- `process_market_a1()` — без змін (просто перейменовано)
- `process_market_stockout()` — NEW Phase A2 orchestrator
- `print_phase_result()` — універсальний вивід для A1 + A2
- 14 колонок stockout_events: EVENT_ID, CLIENT_ID, INN_ID, INN_NAME, DRUGS_ID, DRUGS_NAME, NFC1_ID, STOCKOUT_START/END/WEEKS, PRE_START/END/WEEKS, PRE_AVG_Q
- Дати збережені як datetime64 (нативно у parquet, не string як у канонічному CSV)

**3. EVENT_ID format:** `{CLIENT_ID}_{INN_ID}_{0001}` (4-digit counter per market)

### Smoke-test: market 763807

```bash
python -m pipeline.per_market a2 --market-id 763807
```

Результат: **SUCCESS**

| Метрика | Значення |
|---------|----------|
| INN processed | 610 |
| Raw events | 13,280 |
| **Valid events** | **8,581** |
| Validation rate | 64.6% |
| REJECT no_market_activity | 1,507 (11.3%) |
| REJECT no_pre_sales | 1,515 (11.4%) |
| REJECT no_competitors | 1,677 (12.6%) |
| Drugs with events | 1,279 |
| Output parquet size | 0.20 MB |
| Elapsed | **19.22 sec** |

### Перевірка артефакту stockout_events.parquet

✅ Усі 9 інваріантів пройшли:
1. CLIENT_ID константний
2. EVENT_IDs унікальні
3. Дати — datetime64[ns]
4. STOCKOUT_END >= STOCKOUT_START
5. PRE_END < STOCKOUT_START (1-тижневий gap)
6. STOCKOUT_WEEKS >= 1
7. PRE_WEEKS >= 4 (MIN_PRE_PERIOD_WEEKS)
8. PRE_AVG_Q > 0 (немає degenerate baseline)
9. No NaN у critical колонках

### Статистика
- 8,581 events / 1,279 unique drugs / 485 unique INN
- STOCKOUT_WEEKS: min=1, max=144, median=5
  - Max=144 = майже 3-річний stockout, такі будуть відфільтровані у Phase A3 через POST-validation
- PRE_AVG_Q: median=0.14, max=20.26
- Distribution STOCKOUT_WEEKS: геометричне затухання (1: 1613, 2: 1158, 3: 848, ...) — очікувано

### Validation rate (64.6%) vs канонічного (~80%)
Нижчий показник через те, що це **малий ринок** (137 MB):
- Менше конкурентів → більше `no_competitors` rejects
- Менше INN-активності → більше `no_market_activity` rejects
- Очікуємо вищий rate на середніх/великих ринках

### Bug fix
- `core/stockout.py` self-test використовував Unicode `→` (U+2192) → PowerShell cp1251 не міг encode → fixed на ASCII `->`

### Output
```
data/intermediate/01_per_market/763807/
├── aggregated.parquet         (Phase A1 — 0.92 MB)
└── stockout_events.parquet    (Phase A2 — 0.20 MB) ← NEW
```

### Прогноз масштабування
- 137 MB ринок: A1 = 44s, A2 = 19s → A1+A2 = ~63s
- 754 MB avg ринок: екстраполяція ~5× → ~5 хв per market sequential
- 205 ринків × 5 хв / 6 workers ≈ **2.5-3 години** для A1+A2 повного pipeline

### Наступний крок
**Крок 4: Phase A3 — DiD Analysis.** Перед реалізацією — line-by-line review канонічного `02_03_did_analysis.py` (≈800 рядків — найбільший із кроків Phase A).

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 8: Phase C — Final Export ✅ (END-TO-END WORKING)

### Контекст
Останній методологічний крок — формування **4 фінальних файлів для Power BI**: 2 CSV + 2 XLSX. Це validates повний end-to-end pipeline (Phase A0 → A1 → A2 → A3 → A4 → B → C).

### Узгоджені рішення

| # | Рішення |
|---|---------|
| 1 | Структура колонок (4 mandatory + 5 optional у drug_coef; 3 + 5 у substitute_shares) |
| 2 | `MIN_MARKET_COUNT` як CLI parameter (default 20, smoke-test з 3) |
| 3 | One-shot generation (не progressive — медіана/dip test залежать від всіх ринків) |
| 4 | XLSX без кольорового маркування |

### Виконано

**`pipeline/final_export.py` (NEW, ~480 рядків):**

Функції:
- `load_drug_statistics()` — читає Phase B output
- `load_all_substitute_shares()` — concat substitute_shares.parquet з усіх ринків
- `build_drug_coefficients()` — будує 9-колонковий DataFrame, sort COEF_1 DESC
- `build_substitute_shares()` — LIFT-зважена cross-market агрегація з дедублікацією INTERNAL_LIFT
- `validate_outputs()` — 12 інваріантів
- `write_validation_report()` — текстовий звіт
- `run_final_export(min_market_count)` — orchestrator
- CLI: `--min-market-count N` (default 20)

### Smoke-test з `--min-market-count 3`

```bash
python -m pipeline.final_export --min-market-count 3
```

Результат: **SUCCESS** (всі 12 інваріантів пройшли)

| Метрика | Значення |
|---------|----------|
| Drugs input (Phase B) | 5,120 |
| **Drugs accepted (≥3 markets)** | **2,077 (40.6%)** |
| Drugs rejected | 3,043 |
| **Substitute pairs cross-market** | **38,259** |
| Elapsed | **4.84 sec** |
| Validation | **ALL 12 PASSED** |

### Згенеровані 4 файли (results/final/)

| Файл | Rows | Size |
|------|------|------|
| drug_coefficients.csv | 2,077 | 528 KB |
| drug_coefficients.xlsx | 2,077 | 195 KB |
| substitute_shares.csv | 38,259 | 10.5 MB |
| substitute_shares.xlsx | 38,259 | 2.4 MB |
| validation_report.txt | — | 1.2 KB |

### Усі 12 інваріантів пройшли ✅

**drug_coefficients (6):**
1. ✅ No NaN in COEF_1
2. ✅ COEF_1 ∈ [0, 1]
3. ✅ UNIQUENESS_COEF = 1 - COEF_1 (max diff: 0.0000000)
4. ✅ DRUG_CLASS only {UNIMODAL, MULTIMODAL}
5. ✅ MARKET_COUNT >= 3 (threshold)
6. ✅ DRUGS_ID унікальні

**substitute_shares (6):**
7. ✅ No NaN in SUBSTITUTE_SHARE
8. ✅ SHARE ∈ [0, 1]
9. ✅ **SUM(SHARE per drug) ≈ 1.0** (max diff: 0.000015)
10. ✅ FK constraint: всі DRUGS_ID існують в drug_coef
11. ✅ No duplicate pairs
12. ✅ RANK starts at 1 для всіх drugs

### Реальна перевірка вмісту

**`drug_coefficients.csv` top samples:**
```
ЛЕВОМЕКОЛЬ (мазь):    COEF_1=1.0, MARKET_COUNT=3, UNIMODAL
МОТОПРИД   (табл):    COEF_1=1.0, MARKET_COUNT=3, UNIMODAL
ДОСТИНЕКС  (табл):    COEF_1=1.0, MARKET_COUNT=3, UNIMODAL
БРОНХО-МУНАЛ:         COEF_1=0.998, MARKET_COUNT=4, UNIMODAL
БРУФЕН (сироп):       COEF_1=0.998, MARKET_COUNT=3, UNIMODAL
```

**`substitute_shares.csv` приклад для ТОБРАДЕКС (DRUGS_ID=486):**
```
Rank 1 (38.1%): МЕДЕТРОМ кап. глаз.
Rank 2 (26.3%): ТОБРАДЕКС® мазь глаз.
Rank 3 (16.5%): ТОБИФЛАМИН кап. глаз.
Rank 4 (11.8%): ТОБРОСОПТ-ДЕКС кап. глаз.
Rank 5  (4.9%): ТОБРИНЕКСТ КОМБИ кап. глаз.
Rank 6  (2.5%): ТОБРИНЕКСТ КОМБИ мазь глаз.
SUM = 100% ✓
Усі substitutes SAME_NFC1=True (NFC compatibility filter ✓)
```

### Архітектура pipeline ПОВНІСТЮ РЕАЛІЗОВАНА

```
Raw CSV (DATA_SETS) →
  ▼
Phase A (per-market, parallel × 6 workers):
  A0: discover_markets.py        →  markets_list.csv
  A1: per_market.py a1            →  aggregated.parquet
  A2: per_market.py a2            →  stockout_events.parquet
  A3: per_market.py a3            →  did_events.parquet + substitute_pairs.parquet
  A4: per_market.py a4            →  substitute_shares.parquet
  Runner: pipeline/runner.py     —  ProcessPoolExecutor + resume logic
  ▼
Phase B (cross-market, sequential):
  pipeline/cross_market.py       →  drug_statistics.parquet
  ▼
Phase C (final export):
  pipeline/final_export.py       →  4 фінальних файли + validation_report.txt
```

### Прогноз для повного запуску 205 ринків

З MIN_MARKET_COUNT=20 (default):
- Очікуємо менше drugs у фінальному drug_coefficients.csv (тільки добре-покриті)
- Більше MULTIMODAL drugs (dip test потужніший на більших N)
- Substitute_shares більший (more pairs cross-market)
- Phase B+C разом: ~30-60 секунд

### Наступний крок
**Методологічна частина повністю готова!** Лишається:
- Повний прогон Phase A на 205 ринках (~5-8 годин)
- Запустити Phase B + Phase C → отримати фінальні файли для Power BI
- TUI/launcher (опціонально, для UX)

### Статус: ✅ ЗАВЕРШЕНО — END-TO-END PIPELINE WORKING

---

## 2026-04-27 — Крок 7: Phase B — Cross-Market Aggregation ✅

### Контекст
Перший крок крос-ринкової агрегації. Збираємо did_events.parquet з усіх ринків, обчислюємо MEDIAN_SHARE_INTERNAL per drug + класифікація UNIMODAL/MULTIMODAL через Hartigan dip test.

### Узгоджені рішення (Q-B1...Q-B9)

| # | Рішення | Вибір |
|---|---------|-------|
| Q-B1 | Файл реалізації | `pipeline/cross_market.py` (новий, ~310 рядків) |
| Q-B2 | Per-market drug SHARE | **Ratio of sums**: `SUM(INTERNAL_LIFT) / SUM(TOTAL_EFFECT)` |
| Q-B3 | dip test alpha | 0.05 |
| Q-B4 | Min N для dip test | 4 (інакше default UNIMODAL) |
| Q-B5 | IQR multiplier | 1.5 (Tukey стандарт) |
| Q-B6 | INN_NAME source | Lookup з stockout_events.parquet |
| Q-B7 | Output | `data/intermediate/02_cross_market/drug_statistics.parquet` |
| Q-B8 | DIP_PVALUE як колонка | ✅ Лишаємо (для прозорості) |
| Q-B9 | Skip canonical valid_data_filter | ✅ (фільтр у Phase C) |

### Виконано

**`pipeline/cross_market.py` (NEW, ~310 рядків) — значно простіший за канонічний (2617 рядків!):**

Функції:
- `find_market_dirs()` — знайти всі підпапки з did_events.parquet
- `load_did_events_all()` — concat усіх did_events
- `build_inn_name_lookup()` — INN_ID → INN_NAME з stockout_events
- `aggregate_per_market_drug()` — drug-level SHARE per (CLIENT_ID, DRUGS_ID)
- `iqr_outlier_filter()` — Tukey IQR 1.5×
- `classify_modality()` — Hartigan dip test через `diptest`
- `aggregate_cross_market()` — drug-level cross-market metrics
- `run_cross_market()` — orchestrator
- CLI з `--markets` filter

**`config/paths.py`:** додано `CROSS_MARKET_PATH`

### Smoke-test: 5 ринків з готовими did_events

```bash
python -m pipeline.cross_market
```

Результат: **SUCCESS**

| Метрика | Значення |
|---------|----------|
| Markets found | 5 (29578, 30654, 74521, 75129, 763807) |
| DiD events total | 133,550 |
| Per-market drug pairs | 11,883 |
| **Unique drugs** | **5,120** |
| UNIMODAL | 5,089 (99.4%) |
| MULTIMODAL | 31 (0.6%) |
| Drugs with IQR-filtered outliers | 308 |
| Output size | 0.348 MB |
| Elapsed | **1.74 sec** |

### Валідація drug_statistics.parquet (9 invariants — ALL PASSED)

1. ✅ No NaN in MEDIAN_SHARE_INTERNAL
2. ✅ MEDIAN ∈ [0, 1]
3. ✅ MARKET_COUNT_TOTAL >= 1
4. ✅ MARKET_COUNT_CLEAN <= MARKET_COUNT_TOTAL
5. ✅ MARKET_COUNT_CLEAN >= 1
6. ✅ DRUG_CLASS only {UNIMODAL, MULTIMODAL}
7. ✅ DIP_PVALUE ∈ [0, 1]
8. ✅ Unique DRUGS_ID
9. ✅ INN_NAME populated for all 5,120 drugs (lookup OK)

### Стат розподіл

```
MEDIAN_SHARE_INTERNAL:
  mean    0.5202
  std     0.3256
  min     0.0000
  median  0.5442
  max     1.0000

MARKET_COUNT_TOTAL distribution:
  1 market:  1892 drugs (37.0%)  ← малий dataset (5 ринків)
  2:         1151 (22.5%)
  3:         1001 (19.6%)
  4:          694 (13.6%)
  5:          382 (7.5%)
```

### MULTIMODAL examples

```
DRUGS_ID=63512:  median=0.937, p=0.015, markets=4
DRUGS_ID=226439: median=0.851, p=0.000, markets=4
DRUGS_ID=749550: median=0.784, p=0.007, markets=5
DRUGS_ID=245367: median=0.747, p=0.016, markets=4
DRUGS_ID=959486: median=0.705, p=0.006, markets=4
```

### Output

```
data/intermediate/02_cross_market/
└── drug_statistics.parquet  (10 cols, 5120 rows, 0.35 MB) ← NEW
```

### Прогноз для повного датасету (205 ринків)

При повному запуску очікуємо:
- **~10× більше events** (~1.3M)
- **Більше drugs з coverage >= 20** (зараз 0; потрібно для Phase C MIN_MARKET_COUNT)
- **Більше MULTIMODAL** (dip test потужніший на більших N)
- **Час Phase B зросте до ~10-30 сек** (vs 1.74 сек на 5 ринках)

### Наступний крок
**Крок 8: Phase C — Final Export** (формування 2 CSV + 2 XLSX для Power BI). Це **останній методологічний крок**! Після цього — TUI + .bat launcher + повний запуск.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 6: Parallel Runner + ISSUE-005 FIX ✅

### Контекст
Реалізація паралельного runner-а для запуску Phase A1+A2+A3+A4 на множині ринків. Перед цим виправлено ISSUE-005 (ATC unused).

### Узгоджені рішення

| # | Рішення | Вибір |
|---|---------|-------|
| R1 | MAX_WORKERS | **6** (як у config) |
| R2 | usecols оптимізація (ISSUE-005) | ✅ Так |
| R3 | MIN_MARKET_COUNT = 20 (для Phase C) | ✅ (буде в Phase C) |
| R4 | Smoke-test scope | 5 перших READY ринків |

### Виконано

**1. ISSUE-005 FIX (ATC unused → usecols):**
- `config/column_mapping.py`: додано `USEFUL_COLUMNS` (11 колонок без ATC)
- `pipeline/per_market.py::process_market_a1`: `pd.read_csv(usecols=USEFUL_COLUMNS)`
- Smoke-test на 1439971 (160 MB): SUCCESS, no regression
- `_methods_issues.md`: ISSUE-005 → ✅ FIXED (2 з 12)

**2. `process_market_full()` у per_market.py:**
- Виконує A1→A2→A3→A4 послідовно у одному worker
- **Resume logic**: фази з існуючим parquet output пропускаються (status='skipped')
- Suppress per-phase stdout (worker context — TUI/tqdm на вищому рівні)
- Returns зведений summary з phase-level details

**3. `pipeline/runner.py` (NEW, ~290 рядків):**
- `run_parallel(market_ids, max_workers, force)` — ProcessPoolExecutor orchestrator
- Worker function `_worker_task` → `process_market_full`
- tqdm progress bar з market-id postfix
- `print_runner_summary()` — детальна таблиця з speedup, skip counts, errors
- CLI: `--limit N` / `--all` / `--market-ids ...` / `--workers N` / `--force`

### Smoke-test results: 5 перших READY ринків

```bash
python -m pipeline.runner --limit 5
```

**Файли цих ринків (avg 1065 MB — у 8× більші ніж smoke-test 763807 на 137 MB!):**

| CLIENT_ID | Size MB | Status | Phases |
|-----------|---------|--------|--------|
| 29578 | 1504 | ✅ Complete | A1+A2+A3+A4 |
| 30654 | 761  | ✅ Complete | A1+A2+A3+A4 |
| 70906 | 1793 | ⏸ Partial   | A1+A2 (зупинено вручну на A3) |
| 74521 | 499  | ✅ Complete | A1+A2+A3+A4 |
| 75129 | 765  | ✅ Complete | A1+A2+A3+A4 |

**Прогрес:**
- 1/5 done at 8:41 (521s)
- 2/5 done at 13:10
- 3/5 done at 15:03
- 4/5 done at 17:00
- 5/5 (70906) — зупинено для переходу далі (resume logic зберігає A1+A2)

### Аналіз продуктивності та блокерів

**Чому 8:41 на перший ринок (vs очікуваних 130 сек)?**
Просто smoke-test базовий ринок (137 MB) був у **8× менший** за середній з перших 5 (1065 MB).

| Розмір | Sequential expected | Actual parallel | Speedup |
|--------|---------------------|-----------------|---------|
| 137 MB | 130s (наш baseline) | — | — |
| 499 MB (74521) | 474s | 521s | ~0.9× per-worker |
| 1065 MB avg | ~1015s | (parallel runs) | — |

**Реальний speedup на 4 ринках за 17 хв:**
- Sum sequential: ~62 хв
- Wall-clock parallel: ~17 хв
- **Speedup: 3.6×** (з theoretical 6× — обмеження HDD + long-tail)

**Виявлені блокери (документовано, не виправляємо для демо):**
1. 🟡 **Long-tail problem**: великі ринки (>1.5 GB) монополізують 1 worker, інші idle
2. 🟡 **Phase A3 CPU-bound**: per-event × per-substitute loop повільний на великих
3. 🟢 **Initial HDD contention**: short burst при паралельних reads (не критично)

**Що НЕ є блокером:**
- ❌ HDD (idle при 0% disk time після initial read)
- ❌ RAM (16 GB вільно, ~50%)
- ❌ Memory leaks (gc.collect() між phases)

### Прогноз для повного запуску 205 ринків

```
Total raw: 152 GB
Throughput observed: ~313 MB/min wall-clock
Expected time: ~485 min ≈ 8 годин
```

### Output structure

```
data/intermediate/01_per_market/
├── 29578/  (5 parquet)
├── 30654/  (5 parquet)
├── 70906/  (2 parquet — A1+A2; A3+A4 буде resume при наступному запуску)
├── 74521/  (5 parquet)
├── 75129/  (5 parquet)
├── 763807/ (5 parquet — з попереднього smoke-test)
└── 1439971/(1 parquet — з тесту usecols)
```

### Рішення про подальший рух

Користувач підтвердив:
- Зупиняємо runner (70906 буде resumed при повному запуску)
- Пропускаємо minor optimizations (smart scheduling, MAX_WORKERS=7)
- Переходимо до Phase B (Cross-Market Aggregation)

**Логіка рішення:** Phase B можна реалізувати на 4 готових ринках (smoke-test). Повний запуск на 205 ринках — у фінальній фазі демо-проекту.

### Output: pipeline/runner.py
Working CLI з resume logic, паралельністю, error handling.

### Наступний крок
**Крок 7: Phase B — Cross-Market Aggregation** (line-by-line review канонічного `02_substitution_coefficients/`).

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 5: Phase A4 — Substitute Analysis ✅

### Контекст
Phase A4 — фінальний per-market крок (агрегація substitutes у SUBSTITUTE_SHARE). Завдяки оптимізації Q-A3.3 (LIFT уже у `substitute_pairs.parquet`), наша Phase A4 — лише агрегація без re-computation.

### Узгоджені рішення (Q-A4.1...Q-A4.8)

| # | Рішення | Вибір |
|---|---------|-------|
| Q-A4.1 | Вхід: substitute_pairs.parquet + stockout_events.parquet (для INN_NAME) | ✅ |
| Q-A4.2 | Вихід: substitute_shares.parquet (один файл) | ✅ |
| Q-A4.3 | SUBSTITUTE_SHARE формат — **decimal (0-1)** | ✅ (відповідає фінальним файлам) |
| Q-A4.4 | Без NFC1 декомпозиції (LIFT_SAME/DIFF_NFC1) | ✅ |
| Q-A4.5 | Без stat файлів | ✅ |
| Q-A4.6 | SUBSTITUTE_RANK + EVENTS_COUNT одразу | ✅ |
| Q-A4.7 | INN_NAME через lookup з stockout_events | ✅ |
| Q-A4.8 | Без ThreadPool (vectorized швидко) | ✅ |

### Виконано

**`pipeline/per_market.py` РОЗШИРЕНО:**
- Додано `process_market_substitutes()` (Phase A4 orchestrator, ~200 рядків)
- Subcommand `a4` додано в argparse
- `print_phase_result()` handle phase A4 (з SHARE_SUM invariant індикатором)
- 15 cols `SUBSTITUTE_SHARES_COLUMNS`
- Path helper `get_substitute_shares_path()`
- БЕЗ нових модулів у `core/` — функціонал чисто агрегаційний

### Алгоритм (компактний)

```python
def process_market_substitutes(client_id):
    df_pairs  = pd.read_parquet('substitute_pairs.parquet')   # LIFT уже є
    df_events = pd.read_parquet('stockout_events.parquet')   # для INN_NAME

    # 1. INN_NAME lookup
    inn_name_map = df_events[['INN_ID','INN_NAME']].drop_duplicates().set_index('INN_ID')['INN_NAME']
    df_pairs['INN_NAME'] = df_pairs['INN_ID'].map(inn_name_map)

    # 2. Aggregate per (stockout_drug, substitute_drug)
    df_agg = df_pairs.groupby([...], as_index=False).agg(
        TOTAL_LIFT=('LIFT', 'sum'),
        EVENTS_COUNT=('EVENT_ID', 'count')
    )

    # 3. Zero-LIFT filter
    df_agg = df_agg[df_agg['TOTAL_LIFT'] > 0]

    # 4. INTERNAL_LIFT per stockout_drug
    df_agg['INTERNAL_LIFT'] = df_agg.groupby('STOCKOUT_DRUG_ID')['TOTAL_LIFT'].transform('sum')

    # 5. SUBSTITUTE_SHARE — decimal
    df_agg['SUBSTITUTE_SHARE'] = df_agg['TOTAL_LIFT'] / df_agg['INTERNAL_LIFT']

    # 6. RANK
    df_agg['SUBSTITUTE_RANK'] = df_agg.groupby('STOCKOUT_DRUG_ID')['SUBSTITUTE_SHARE'].rank(method='first', ascending=False).astype(int)

    save_parquet(df_agg, 'substitute_shares.parquet')
```

### Smoke-test: market 763807

```bash
python -m pipeline.per_market a4 --market-id 763807
```

Результат: **SUCCESS**

| Метрика | Значення |
|---------|----------|
| Input pairs (з substitute_pairs) | 28,621 |
| After aggregation (unique pairs) | 5,842 |
| Filtered zero-LIFT | 969 (16.6%) |
| **Final pairs** | **4,873** |
| Stockout drugs | 833 |
| Unique substitutes | 1,178 |
| **SHARE_SUM invariant** | **PASSED** (max diff: 0.0000050) |
| Output size | 0.20 MB |
| Elapsed | **0.18 sec** ⚡ |

⚡ **Швидкість 0.18 sec** — на 2 порядки швидше за канонічний (re-computation на десятках тисяч подій). Це результат архітектурної оптимізації: у Phase A3 ми зберегли LIFT — тут просто агрегуємо.

### Перевірка артефакту (11 invariants)

✅ Усі 11 пройшли:
1. CLIENT_ID константний
2. STOCKOUT_DRUG_ID ≠ SUBSTITUTE_DRUG_ID
3. TOTAL_LIFT > 0 (zero-filter)
4. INTERNAL_LIFT > 0
5. TOTAL_LIFT ≤ INTERNAL_LIFT (sanity)
6. SUBSTITUTE_SHARE ∈ (0, 1] (decimal format works)
7. EVENTS_COUNT >= 1
8. SUBSTITUTE_RANK >= 1
9. RANK consistency (1..N no gaps within stockout)
10. **SUM(SHARE) per stockout drug = 1.0** — max diff 0.0000050 ⭐
11. No NaN in critical cols

### Статистика результатів
```
Stockout drugs:           833 (з 1,030 у did_events; решта мали тільки zero-LIFT pairs)
Unique substitutes:       1,178
Avg substitutes per drug: 5.85
SAME_NFC1 ratio:          81.3%
Avg SHARE (rank=1):       0.629  (top substitute типово захоплює ~63% INTERNAL_LIFT)
Median EVENTS_COUNT:      4
```

### Output structure після Phase A4

```
data/intermediate/01_per_market/763807/
├── aggregated.parquet         (Phase A1, 0.92 MB)
├── stockout_events.parquet    (Phase A2, 0.20 MB)
├── did_events.parquet         (Phase A3, 0.33 MB)
├── substitute_pairs.parquet   (Phase A3, 0.37 MB)
└── substitute_shares.parquet  (Phase A4, 0.20 MB) ← NEW
```

### Прогноз масштабування Phase A1+A2+A3+A4
- 137 MB ринок: 44+19+65+0.18 ≈ **128 секунд**
- Avg 754 MB ринок: ~5× → ~10-11 хв per market sequential
- 205 ринків × 10 хв / 6 workers ≈ **5-6 годин** для повного A1+A2+A3+A4

### Наступний крок
**Phase A — повністю завершена** для одного ринку. Лишається:
- **Phase B** — Cross-Market Aggregation (зібрати усі substitute_shares.parquet з 205 ринків, IQR-фільтр, dip test для UNIMODAL/MULTIMODAL, медіани)
- **Phase C** — Final Export (2 CSV + 2 XLSX для Power BI)
- **Phase D** — Parallel Runner + TUI + .bat launcher

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 4: Phase A3 — DiD Analysis ✅

### Контекст
Реалізація Phase A3 з канонічною логікою + одне математичне виправлення (ISSUE-013).

### Узгоджені рішення (Q-A3.0...Q-A3.8)

| # | Рішення | Вибір |
|---|---------|-------|
| Q-A3.0 | LOST_SALES bug (canonical double-subtracts target_pre) | **Опція B: FIX** + ISSUE-013 |
| Q-A3.1 | Вхід: aggregated.parquet + stockout_events.parquet | ✅ |
| Q-A3.2 | Вихід: 2 parquet (did_events + substitute_pairs) | ✅ |
| Q-A3.3 | LIFT у substitute_pairs (оптимізація — не перераховуємо у Phase A4) | ✅ |
| Q-A3.4 | Прибрати NFC1 декомпозицію (LIFT_SAME_NFC1 etc.) | ✅ — лишаємо лише `SAME_NFC1` flag |
| Q-A3.5 | Прибрати CRITICAL/SUBSTITUTABLE класифікацію | ✅ |
| Q-A3.6 | Без `did_summary.csv`, `drugs_summary.csv`, `did_metadata.csv` | ✅ |
| Q-A3.7 | Без ThreadPool (CPU без HT) | ✅ |
| Q-A3.8 | `core/did.py` + `core/nfc.py` нові модулі | ✅ |

### ⚠️ ISSUE-013 (FIXED) — короткий опис

Канонічний код `02_03_did_analysis.py:437-441` подвійно віднімає `target_pre` від `MARKET_TOTAL_DRUGS_PACK` яке вже competitors-only. Систематичний bias: завищує LOST_SALES, занижує SHARE_INTERNAL у канонічному.

**Наша реалізація:** `comp_pre = market_total_pre` (без подвійного віднімання). Математично коректно. Документовано як ISSUE-013 🔴 HIGH у `_methods_issues.md`.

### Виконано

**1. `core/nfc.py` (NEW, 130 рядків):**
- 1-в-1 копія canonical `nfc_compatibility.py`
- ORAL_GROUP (3 пероральні форми) + EXCLUDE_FORMS
- `is_compatible()`, `get_compatibility_group()`
- Self-test PASSED

**2. `core/did.py` (NEW, 380 рядків) — з ISSUE-013 FIX:**
- `define_post_period()` — 4 statuses (valid / no_recovery / gap_too_large / insufficient_data)
- `calculate_market_growth()`, `calculate_expected()`, `calculate_lift()`, `calculate_shares()`
- `find_valid_substitutes()` — NFC + Phantom filter
- **`calculate_did_for_event()` — main DiD з ВИПРАВЛЕНИМ LOST_SALES** (returns event metrics + substitute pairs з LIFT)
- Self-test PASSED

**3. `pipeline/per_market.py` РОЗШИРЕНО:**
- `process_market_did()` — Phase A3 orchestrator
- Subcommand `a3` додано в argparse
- `print_phase_result()` — handle phase A3 (special output для 2 parquet файлів)
- Updated docstring + CLI epilog
- 20 cols `DID_EVENTS_COLUMNS`, 14 cols `SUBSTITUTE_PAIRS_COLUMNS`

**4. CLI:** `python -m pipeline.per_market a3 --market-id N` або `--limit N`

### Smoke-test: market 763807

```bash
python -m pipeline.per_market a3 --market-id 763807
```

Результат: **SUCCESS**

| Метрика | Значення |
|---------|----------|
| Events input (з stockout_events.parquet) | 8,581 |
| **Valid DiD events** | **5,350** (62.3%) |
| REJECT no_post_period | 1,188 (13.8%) |
| Info no_substitutes (still processed) | 1,527 (17.8%) |
| REJECT no_effect | 2,043 (23.8%) |
| **Substitute pairs** | **28,621** |
| did_events parquet size | 0.33 MB |
| substitute_pairs parquet size | 0.37 MB |
| Elapsed | **64.95 sec** |

### Перевірка артефактів

✅ **did_events.parquet (12 invariants):**
- CLIENT_ID константний, EVENT_IDs унікальні
- POST_STATUS == 'valid', POST_WEEKS == 4
- SHARE_INTERNAL + SHARE_LOST = 1.0 (max diff: 0.000000)
- SHARE значення ∈ [0, 1]
- TOTAL_EFFECT >= 0.001
- INTERNAL_LIFT, LOST_SALES, MARKET_GROWTH >= 0
- SUBSTITUTES_WITH_LIFT <= SUBSTITUTES_COUNT

✅ **substitute_pairs.parquet (9 invariants):**
- EVENT_IDs ∈ did_events (FK constraint)
- TARGET != SUBSTITUTE
- SAME_NFC1 має both True/False
- SALES_PRE, SALES_DURING, EXPECTED, LIFT >= 0
- LIFT == max(0, SALES_DURING - EXPECTED) (formula consistency)

✅ **Cross-file invariant:** `INTERNAL_LIFT (did_events) == sum(LIFT) (substitute_pairs)` per event
- Max diff: **0.000200** (rounding)
- 0 events with diff > 0.01

### Статистика результатів

```
Avg SHARE_INTERNAL: 0.460  (46% retained)
Avg SHARE_LOST:     0.540  (54% lost to competitors)
Avg MARKET_GROWTH:  3.898  (PRE→DURING volume ratio; інтерпретується через тривалість stockouts)
Unique drugs:       1,030  (з 1,279 з stockout events)
Avg pairs per event:5.3
SAME_NFC1 ratio:    82.8%  (більшість substitutes — same form)
LIFT > 0 pairs:     36.7%  (zero-LIFT відфільтрується у Phase A4)
```

### Output structure

```
data/intermediate/01_per_market/763807/
├── aggregated.parquet         (Phase A1, 0.92 MB)
├── stockout_events.parquet    (Phase A2, 0.20 MB)
├── did_events.parquet         (Phase A3, 0.33 MB) ← NEW
└── substitute_pairs.parquet   (Phase A3, 0.37 MB) ← NEW
```

### Прогноз масштабування
- A1+A2+A3 на 137 MB ринку: 44+19+65 = **128 секунд**
- Avg 754 MB ринок: ~5× → ~10-11 хв per market sequential
- 205 ринків × 10 хв / 6 workers ≈ **5-6 годин** для повного A1+A2+A3

### Bug fix
- `core/did.py` self-test використовував Unicode `→` → fixed до ASCII `->`

### Наступний крок
**Крок 5: Phase A4 — Substitute Analysis.** Завдяки оптимізації Q-A3.3 (LIFT уже у `substitute_pairs.parquet`), Phase A4 буде простою агрегацією — економія часу.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 3-prep: Phase A2 review + створення `_methods_issues.md` 🔄

### Контекст
Перед реалізацією Phase A2 — детальний line-by-line review канонічного `02_02_stockout_detection.py` (599 рядків). Узгоджено Q-A2.1...Q-A2.7 (parquet вхід/вихід, 14 колонок без NFC_ID/MARKET_DURING_Q, subcommand CLI). Користувач запитав детальний розбір 3-рівневої валідації.

### Розгорнута дискусія методології
Розглянули:
1. **Level 1 (Market Activity, INN-level)** — бізнес-логіка + чому INN не drug
2. **Level 2 (PRE-period Sales, drug-level)** — математична необхідність baseline
3. **Level 3 (Competitors Availability, drug-level)** — для коректного SHARE_LOST

При запитанні "чи це математично та бізнес-логічно правильно" — провели **критичний професійний аналіз** із виявленням слабких місць.

### Рішення
**Залишаємо канонічну логіку 1-в-1** (опція A), бо:
- Це презентаційний демо-проект, не методологічне дослідження
- Канонічна методологія валідована
- Покращення = окремий проект з валідацією

**Але** — створюємо живий tech-debt документ для майбутніх удосконалень.

### Виконано

**Створено `_methods_issues.md` (новий 4-й живий документ)**:
- 11 виявлених issues (5 ⭐, 6 ⭐⭐, 0 ⭐⭐⭐)
- 0 🔴 HIGH, 7 🟡 MEDIUM, 4 🟢 LOW
- Структура: severity × effort × proposed fix × acceptance rationale
- Покриває: Phase A0 (1), Phase A1 (4), Phase A2 (7)

**Перелік issues:**
- ISSUE-001: Sniff-валідація лише на 3 рядках
- ISSUE-002: INN_ID dtype float64 quirk
- ISSUE-003: NOTSOLD бінарні пороги без врахування volume
- ISSUE-004: Memory pressure на 1.5-2 GB файлах
- ISSUE-005: ATC коди читаються, але не використовуються
- ISSUE-006: Level 1 бінарний поріг `> 0`
- ISSUE-007: Level 2 бінарний поріг `pre_sales == 0`
- ISSUE-008: PRE-період 4 тижні короткий
- ISSUE-009: PRE_AVG mean чутливе до викидів
- ISSUE-010: Level 3 бінарний поріг
- ISSUE-011: Level 3 не порівнюється з PRE
- ISSUE-012: POST-validation відкладена на A3

**Оновлено `ROADMAP.md` §12** — `_methods_issues.md` тепер 4-й живий документ.

### Output
`drug_substitution_engine/_methods_issues.md` (~600 рядків, з 11 ISSUE)

### Принципи ведення `_methods_issues.md`
- Поповнюється в міру виявлення нових слабкостей у наступних phases
- Severity: 🟢 LOW / 🟡 MEDIUM / 🔴 HIGH
- Effort: ⭐ годин / ⭐⭐ днів / ⭐⭐⭐ тижнів
- Кожен ISSUE має: опис, приклад, поточну поведінку, запропоноване покращення, вплив, обґрунтування "as-is"

### Наступний крок
**Реалізація Phase A2** з канонічною логікою:
1. `core/stockout.py` (NEW): `identify_stockout_periods` + `validate_stockout_event`
2. `pipeline/per_market.py`: + `process_market_stockout()` + subcommand argparse
3. Smoke-test `a2 --market-id 763807`
4. Перевірка артефакту `stockout_events.parquet`

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 2: Phase A1 — Data Aggregation ✅

### Контекст
Після узгодження Q-A1.1...Q-A1.7 та реалізації size filter — реалізація Phase A1 за 4 під-задачі поспіль, smoke-test, перевірка артефакту.

### Виконано

**1. `requirements.txt` + venv:**
- Додано `pyarrow>=15.0.0` (для parquet)
- Встановлено: pyarrow 24.0.0 (~28 MB)

**2. `config/stockout_params.py` (NEW, 70 рядків):**
- Параметри Phase A1 (NOTSOLD): `MIN_NOTSOLD_PERCENT=0.20`, `MAX_NOTSOLD_PERCENT=0.95`
- Параметри Phase A2 (Stockout): `MIN_STOCKOUT_WEEKS=1`, `MIN_PRE_PERIOD_WEEKS=4`
- Параметри Phase A3 (DiD): `MIN_POST_PERIOD_WEEKS=4`, `MAX_POST_GAP_WEEKS=2`, ...
- Усі скопійовано з канонічного без змін, validation на import

**3. `core/etl.py` РОЗШИРЕНО (з 117 → ~280 рядків):**
- Залишено: `parse_period_id`, `parse_period_id_series`, `align_to_monday`
- Додано: `convert_numeric_columns`, `rename_columns`, `add_date_column`
- Додано: `fill_gaps` (vectorized, з gap_filling per (PHARM_ID, DRUGS_ID))
- Додано: `aggregate_weekly`, `calculate_market_totals`, `calculate_notsold_percent`
- Self-test PASSED: parse, convert, fill_gaps (synthetic gap → Q=0), notsold

**4. `pipeline/per_market.py` (NEW, ~400 рядків):**
- `process_inn(df_inn, ...)` — обробка одного INN: gap fill → aggregate → split → NOTSOLD filter → market_totals → merge
- `process_market(client_id, file_path)` — повний pipeline Phase A1 для одного ринку, повертає dict з метриками + drugs_df
- CLI: `--market-id N` для одного, `--limit N` для перших N (sequential)
- Output: `data/intermediate/01_per_market/{CLIENT_ID}/aggregated.parquet`
- Engine: pyarrow, compression: snappy
- Rich TUI: красивий вивід Panel + Table

**5. Bug fix:** `config/paths.py::load_markets_list()` не передавав `sep=';'` → виправлено на `sep=CSV_SEPARATOR`.

### Smoke-test: market 763807 (137 MB — найменший READY)

```bash
python -m pipeline.per_market --market-id 763807
```

Результат: **SUCCESS**

| Метрика | Значення |
|---------|----------|
| Status | SUCCESS |
| Raw rows | 339,642 |
| Output rows | 161,636 (target only) |
| INN processed | 610 |
| INN skipped | 706 (no valid drugs after NOTSOLD filter) |
| Unique DRUGS_ID | 1,850 |
| Output parquet size | **0.92 MB** |
| Compression vs raw CSV | ~150× |
| Elapsed | **43.89 sec** |

### Валідації артефакту (через `pd.read_parquet`)

| Перевірка | Результат |
|-----------|-----------|
| Shape | (161636, 13) |
| All `PHARM_ID == 763807` | ✅ |
| `NOTSOLD_PERCENT ∈ [0.20, 0.95]` | ✅ min=0.200, max=0.950 |
| Date dtype | datetime64[ns] |
| Q=0 присутні (gap fill OK) | ✅ 138,043 рядки |
| MARKET_TOTAL NaN count | 0 |
| Date range | 2023-01-02 → 2026-04-13 |

### Виявлений мінорний нюанс
- `INN_ID dtype = float64` (а не `int64`) через NaN propagation у `fill_gaps` під час merge.
- Не критично: усі downstream операції працюють (`==`, groupby з `INN_ID` як float OK).
- За потреби виправити в Phase A2 через `df['INN_ID'].astype('int64')` (після перевірки на NaN).

### Колонки парquet (13)
`PHARM_ID, DRUGS_ID, Date, Q, V, DRUGS_NAME, INN_NAME, INN_ID, NFC1_ID, NFC_ID,
 NOTSOLD_PERCENT, MARKET_TOTAL_DRUGS_PACK, MARKET_TOTAL_DRUGS_REVENUE`

### Прогноз на масштабування
- 137 MB → 44 сек на 1 ринок (1 worker)
- Avg ринок: 754 MB ≈ 5.5× → ~4 хв на ринок (sequential)
- 205 ринків × 4 хв / 6 workers ≈ **2.0-2.5 години** загалом для Phase A1

(Точний час буде заміряно після Кроку 7 — паралельний runner)

### Наступний крок
**Крок 3: Phase A2 — Stockout Detection.** Перед реалізацією — line-by-line review канонічного `02_02_stockout_detection.py`.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 2-prep: Phase A1 architectural decisions + size filter ✅

### Контекст
Перед реалізацією Phase A1 (Data Aggregation) узгодили line-by-line модифікації канонічного `02_01_data_aggregation.py` та доповнили memory protection.

### Узгоджені рішення (Q-A1.1 ... Q-A1.7)

| # | Рішення | Вибір |
|---|---------|-------|
| Q-A1.1 | Структура виходу Phase A1 | **B: 1 parquet per market** (баланс memory + speed + resume) |
| Q-A1.2 | Окремий summary CSV per market | ❌ Прибираємо (не використовується downstream) |
| Q-A1.3 | Збір drugs_list під час A1 | ✅ Так, агрегуємо після workers |
| Q-A1.4 | NOTSOLD фільтр (0.20-0.95) | ✅ Залишаємо як в каноні |
| Q-A1.5 | Параметри stockout/notsold | ✅ Скопіюємо в `config/stockout_params.py` |
| Q-A1.6 | Формат intermediate | **Parquet** (3-5× менше CSV, 2× швидший I/O) |
| Q-A1.7 | Parquet engine | **pyarrow** (стандарт, швидший за fastparquet) |

### Memory protection — `MAX_FILE_SIZE_MB` filter

**Проблема:** при 6 workers × файли 1.5-2 GB пік RAM ~30 GB → ризик OOM на 32 GB машині.

**Альтернативи розглянуті:**
- A. Видалити >2GB файли (2 файли, ~4 GB)
- B. Config filter `MAX_FILE_SIZE_MB` без видалення
- C. Smart scheduling

**Вибрано B** — реверсивно, файли на диску, легко змінити поріг.

### Реалізовано

**1. `config/machine_params.py`:**
```python
MAX_FILE_SIZE_MB = 2048   # 2 GB поріг
```
Документовано: можна знизити до 1500 при OOM, або підняти при запасі.

**2. `pipeline/discover_markets.py`:**
- Додано `STATUS_OVERSIZED` константу
- В `sniff_market_file()` після всіх валідацій — перевірка `FILE_SIZE_MB > MAX_FILE_SIZE_MB`
- Summary тепер має 4 категорії: READY / OVERSIZED / EMPTY / MALFORMED
- Sort order: READY → OVERSIZED → EMPTY → MALFORMED

### Результат повторного discovery

```
Total: 207
READY:     205
OVERSIZED:   2  (4270496.csv 2193 MB, 370875.csv 2054 MB)
EMPTY:       0
MALFORMED:   0
Elapsed: 1.51 s
```

### Output
`data/intermediate/00_preproc/markets_list.csv` — 205 READY + 2 OVERSIZED

### Наступний крок
Реалізація Phase A1: розширення `core/etl.py`, створення `config/stockout_params.py` та `pipeline/per_market.py`.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 1b: Повний discovery на 207 файлах ✅

### Контекст
Користувач підтвердив рекомендацію — спершу запустити повний discovery (~5 сек), потім переходити до Кроку 2.

### Виконано
```bash
python -m pipeline.discover_markets
```

### Результат
| Метрика | Значення |
|---------|----------|
| Total files | 207 |
| READY | 207 |
| EMPTY | 0 |
| MALFORMED | 0 |
| Elapsed | **3.64 сек** (швидше за прогноз 4-5 сек) |

### Додаткова валідація
- ✅ Усі 207 CLIENT_ID унікальні
- ✅ 0 mismatches: `filename.split('.csv')[0] == CLIENT_ID` для всіх 207 файлів — підтвердження що мапінг через вміст коректний (хоч в цьому датасеті імена і так збігаються з CLIENT_ID, ми все одно не залежимо від цієї конвенції)

### Статистика файлів
```
Min:    137.59 MB
Max:    2193.47 MB  (4270496.csv) ⚠️ важливо для пам'яті в Phase A1
Mean:   753.64 MB
Median: 678.60 MB
Total:  152.35 GB
```

### Top 10 найбільших файлів (для memory planning Phase A1)
| CLIENT_ID | Size MB |
|-----------|---------|
| 4270496 | 2193.47 |
| 370875  | 2054.17 |
| 1181224 | 1941.08 |
| 745027  | 1902.05 |
| 3190465 | 1900.27 |
| 782986  | 1794.28 |
| 70906   | 1793.25 |
| 3284195 | 1777.47 |
| 1605028 | 1750.21 |
| 4448454 | 1725.26 |

### Висновки для Phase A1 (memory planning)
- Найбільший файл 2.2 GB → DataFrame у RAM може бути ~3-5 GB (pandas overhead)
- При 6 workers, якщо випадково всі обробляють великі файли: пік ~18-30 GB → межа 32 GB RAM
- **Мітигація**: розглянути dtype-оптимізацію при `read_csv`, можливо chunksize для найбільших файлів, або динамічне обмеження workers коли в черзі великі файли

### Output
`data/intermediate/00_preproc/markets_list.csv` — 207 рядків, всі STATUS=READY

### Наступний крок
**Крок 2: Phase A1 — Data Aggregation**. Перед реалізацією — line-by-line review канонічного `02_01_data_aggregation.py` для узгодження модифікацій.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 0e: Створення живих документів (LOGS, ALGORITHMS) 🔄

### Контекст
Узгоджено з користувачем структуру 3 живих документів у корені проекту: ROADMAP, LOGS, ALGORITHMS — для безперервності сесії після можливих збоїв або компактингу контексту.

### Виконано
- Оновлено `ROADMAP.md` до v0.2 (всі ухвалені рішення зафіксовано)
- Створено `LOGS.md` (цей файл)
- Створено `ALGORITHMS.md` (поточно — скелет; буде наповнюватися крок за кроком)

### Output
```
drug_substitution_engine/
├── ROADMAP.md                  ← v0.2 (оновлено)
├── LOGS.md                     ← NEW
├── ALGORITHMS.md               ← NEW (скелет)
└── requirements.txt            ← без змін
```

### Наступний крок
Крок 1: створення скелета проекту (`config/`, `pipeline/`) + реалізація preprocessing (`discover_markets.py`)

### Статус: 🔄 У ПРОЦЕСІ

---

## 2026-04-27 — Крок 0c-0d: Python env + NFC scope ✅

### Контекст
Користувач повідомив, що на ПК працюють інші розробники, які просили не торкатись глобальних бібліотек. Узгоджено створення shared venv в `D:\RADYSLAV_PROJECTS\lib_env\`.

### Виконано

**1. Перевірка наявних Python:**
- Знайдено: Python 3.10.11 та 3.13.1 у user-папці `C:\Users\maksym.dmytrenko\AppData\Local\Programs\Python\`
- Підтверджено: ці Python знаходяться в персональній папці користувача — інші розробники мають свої
- Conda не встановлена (і не потрібна)
- Канонічний `.venv` зламаний на Windows (mac-style `bin/`) — не використовуємо

**2. Створення venv:**
```powershell
py -3.13 -m venv "D:\RADYSLAV_PROJECTS\lib_env"
```
- Python всередині venv: 3.13.1
- pip оновлено: 24.3.1 → 26.1 (всередині venv)

**3. Створено requirements.txt:**
```
pandas>=2.2.0, <3.0.0      # 2.3.3 — як у канонічному
numpy>=2.0.0, <3.0.0       # 2.4.4
scipy>=1.12.0              # 1.17.1
diptest>=0.9.0             # 0.11.0 — Hartigan's dip test
openpyxl>=3.1.0            # 3.1.5
xlsxwriter>=3.1.0          # 3.2.9
tqdm>=4.66.0               # 4.67.3
rich>=13.0.0               # 15.0.0
```

**4. Встановлення (одна команда):**
```powershell
"D:\RADYSLAV_PROJECTS\lib_env\Scripts\pip.exe" install -r requirements.txt --no-cache-dir
```

**5. Виправлення pandas 3.0 → 2.3.3:**
- Pip автоматично встановив pandas 3.0.2 (latest), який має breaking changes
- Зафіксовано у requirements.txt: `pandas>=2.2.0, <3.0.0`
- Даунгрейд до pandas 2.3.3 (відповідає канонічному проекту)

**6. NFC scope decision:**
Узгоджено що залишається в pipeline:
- ✅ `nfc_compatibility.py` — фільтр сумісності форм випуску (критично для коректних substitutes)
- ✅ NFC1_ID як колонка в потоці даних
- ✅ `SAME_NFC1` bool флаг в `substitute_shares.csv` (опційна колонка)

Що прибираємо:
- ❌ Окремі довідники `nfc1_list.csv`, `nfc2_list.csv`
- ❌ NFC2_ID обробка взагалі
- ❌ NFC1 декомпозиція в DiD (`LIFT_SAME_NFC1`, `SHARE_SAME_NFC1` тощо)

### Output
```
D:\RADYSLAV_PROJECTS\
├── lib_env\                    ← shared venv (~270 MB)
│   └── Scripts\python.exe     ← Python 3.13.1 (ізольований)
└── drug_substitution_engine\
    └── requirements.txt        ← 8 пакетів, всі pinned
```

### Метрики
- Розмір venv: ~270 MB
- Час установки: ~30 секунд (pip + 8 пакетів)
- Підтверджено: всі 8 пакетів імпортуються без помилок

### Рішення
1. **venv shared в `D:\RADYSLAV_PROJECTS\lib_env\`** — для всіх RADYSLAV проектів
2. **Python 3.13.1** як база (відповідає канонічному)
3. **pandas pinned <3.0** — щоб канонічний код працював без модифікацій під 3.0 API
4. **NFC scope мінімальний** — тільки фільтр + SAME_NFC1 флаг

### Наступний крок
Створити LOGS.md та ALGORITHMS.md, потім перейти до Кроку 1 (skeleton + preprocessing).

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 0a-0b: Hardware analysis + Storage strategy ✅

### Контекст
Перед налаштуванням Python env потрібно було визначити параметри ПК для конфігурації паралельності, та вирішити чи розміщувати дані на SSD або HDD.

### Виконано

**1. Аналіз hardware:**
```
CPU:    Intel Core i7-9700F, 8 фізичних / 8 логічних, 3.0 GHz (без HT)
RAM:    31.94 GB
OS:     Windows 10 Pro
D:      HDD (Seagate 2TB), вільно 1123 GB
C:      NVMe SSD (Samsung 970 EVO 500GB), вільно лише 23.86 GB ⚠️
```

**2. Аналіз можливості розміщення на SSD:**
- Датасет `pd_ds_4_pres`: **152.35 GB** (avg 754 MB/файл, max 2.2 GB)
- SSD вільно: 23.86 GB
- Вердикт: ❌ **Неможливо** розмістити на SSD без масштабного очищення системного диску (ризиковано)

**3. Storage strategy decision:**
- Усе на D: (HDD): raw + intermediate + results + venv
- Стратегія мітигації HDD-затримок:
  - Кожен worker читає свій файл цілком в RAM (sequential)
  - Процесинг — повністю в RAM (32 GB вистачає)
  - Мінімум проміжних read/write
  - Уникаємо re-read raw файлів

**4. Параметри паралельності розраховані:**
```python
MAX_WORKERS          = 6     # 8 ядер - 1 (ОС) - 1 (main/UI)
THREADS_PER_WORKER   = 1     # без HT — потоки лише overhead
RAM_PER_WORKER_GB    = 2.0   # бюджет на worker (peak ~800 MB файл + DataFrame)
MARKET_TIMEOUT_SEC   = 3600  # 60 хв per market
```

### Output
- Параметри зафіксовані для подальшого `config/machine_params.py`

### Рішення
1. **Все на D:** (raw read-only з DATA_SETS, intermediate + results у проекті)
2. **HDD-aware стратегія I/O:** мінімум disk I/O, всі обчислення в RAM
3. **6 workers** оптимально для цього CPU
4. **Без INN-thread parallelism** (THREADS_PER_WORKER = 1) на цьому CPU без HT

### Наступний крок
Створити venv та встановити залежності.

### Статус: ✅ ЗАВЕРШЕНО

---

## 2026-04-27 — Крок 0: Initial analysis + ROADMAP draft ✅

### Контекст
Початок проекту. Користувач звернувся за створенням нового проекту `drug_substitution_engine` для презентації мережі **the pharmacy chain** — на базі канонічного `cross_pharm_market_analysis`, але з модифікаціями для специфічних 4 файлів-результатів.

### Виконано

**1. Глибокий аналіз канонічного проекту:**
- Прочитано всю документацію `cross_pharm_market_analysis/docs/` (00_ai_rules, 01_did_processing, 02_substitution_coefficients, _project_history, _project_tech_parameters, _temp_project_plan)
- Прочитано всі ключові скрипти: `01_preproc.py`, `02_01_data_aggregation.py`, `03_final_output/01_drug_coefficients.py`, `03_final_output/02_substitute_shares.py`, `parallel_runner.py`, `paths_config.py`, `column_mapping.py`, `etl_utils.py`, `did_utils.py`, `nfc_compatibility.py`
- Прочитано конфіги: `machine_parameters.py`, `coverage_thresholds.py`, `reliability_thresholds.py`, `stockout_params.py`, `classification_thresholds.py`
- Перевірено результати канонічного: 99 ринків, 507 препаратів досліджено, 306 в Phase 3 (`MARKET_COUNT >= 20`), валідації 7/7 PASSED для обох Phase 3 кроків

**2. Аналіз нових даних (`DATA_SETS/pd_ds_4_pres`):**
- 207 CSV файлів
- Структура колонок ідентична канонічному
- Імена файлів `{CLIENT_ID}.csv` (без `Rd2_` префіксу)
- PERIOD_ID range: 202300001 — 202600104 (ті ж 3 роки)
- ⚠️ Файли значно більші: avg 754 MB, max 2.2 GB
- ⚠️ Загальний обсяг: 152.35 GB (~35× від канонічного)

**3. Узгоджено зі замовником ключові рішення:**
- Це окреме нове дослідження, не заміна канонічного
- Дані — демонстраційні (Харків), не справжній the pharmacy chain
- 207 ринків — демонстраційний обсяг
- Структуру можна спрощувати vs канонічний — головна мета: 2 CSV + 2 XLSX
- CLIENT_ID мапінг через **вміст файлу** (колонку), не імʼя
- ORG_ID == CLIENT_ID → target pharmacy в кожному файлі
- Hartigan's dip test для UNIMODAL/MULTIMODAL — підтверджено
- Опційні колонки на мій розсуд
- N=1 препарати автоматично вилучаються через `MIN_MARKET_COUNT >= 20`
- Формат запуску: `.bat` launcher + Python TUI (rich)

### Output
- `D:\RADYSLAV_PROJECTS\drug_substitution_engine\` (порожня папка створена)
- `ROADMAP.md` (v0.1 — perший draft з планом)

### Метрики
- Прочитано документації: ~3000 рядків
- Прочитано скриптів: ~2500 рядків
- Розмір ROADMAP: ~330 рядків

### Наступний крок
Аналіз hardware ПК + storage strategy.

### Статус: ✅ ЗАВЕРШЕНО

---
