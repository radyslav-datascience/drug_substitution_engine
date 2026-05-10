# METHODS ISSUES — `drug_substitution_engine`

> **Версія:** 1.0
> **Створено:** 2026-04-27
> **Призначення:** живий журнал виявлених слабких місць методології та алгоритмів. Поточний продакшен-pipeline залишається з канонічною логікою (опція A) для презентаційного проекту, а цей документ фіксує **технічний борг** для майбутнього вдосконалення.
> **Оновлення:** додавати нові записи в міру виявлення проблем у наступних фазах.

---

## ПРИНЦИПИ ВЕДЕННЯ

### Що сюди записуємо
- Методологічні слабкості (бінарні пороги, чутливість до викидів, тощо)
- Алгоритмічні нюанси (memory pressure, dtype quirks)
- Edge-cases що канонічна логіка обробляє неоптимально
- Спрощення зроблені свідомо для демо, які варто відкатати в продакшені

### Що **НЕ** сюди
- Звичайні баги (виправляються одразу)
- Не-методологічні TODO (це в інших документах)

### Шаблон запису

```markdown
### ISSUE-XXX: коротка назва

**Phase:** AN.M
**Реалізація:** `path/to/file.py:line`
**Severity:** 🟢 LOW / 🟡 MEDIUM / 🔴 HIGH
**Effort to fix:** ⭐ (години) / ⭐⭐ (дні) / ⭐⭐⭐ (тижні)
**Status:** ✅ Documented / 🔄 Being addressed / ❌ Won't fix

#### Опис проблеми
(зрозумілою мовою з прикладом)

#### Поточна поведінка
```python
# код як зараз
```

#### Запропоноване покращення
```python
# як могло б бути
```

#### Вплив на результати
(оцінка bias, edge cases)

#### Обґрунтування "as-is" (чому залишаємо)
(посилання на ROADMAP/контекст рішення)
```

### Класифікація severity

| Рівень | Що означає |
|--------|-----------|
| 🟢 LOW | Косметичне, edge-case з мінімальним впливом |
| 🟡 MEDIUM | Помірний bias на ~5-15% подій, не катастрофа |
| 🔴 HIGH | Може давати некоректні результати, треба фіксити обов'язково |

### Класифікація effort

| Рівень | Що означає |
|--------|-----------|
| ⭐ | Години — простий fix, локальна зміна |
| ⭐⭐ | Дні — нові параметри, можливо тести |
| ⭐⭐⭐ | Тижні — нове методологічне дослідження + валідація |

---

# PHASE A0 — DISCOVERY

## ISSUE-001: Sniff-валідація колонок тільки на перших 3 рядках

**Phase:** A0
**Реалізація:** `pipeline/discover_markets.py::sniff_market_file`
**Severity:** 🟢 LOW
**Effort to fix:** ⭐
**Status:** ✅ Documented

### Опис проблеми

Discovery читає лише `nrows=3` для отримання `CLIENT_ID` та валідації колонок. Якщо файл має:
- неконстантний `CLIENT_ID` десь у середині (що теоретично можливо при склейці двох ринків),
- битий рядок десь нижче,
- неправильну назву колонки лише в певних рядках,

— ми цього **не виявимо** на етапі discovery. Помилка проявиться лише в Phase A1, коли worker почне читати повний файл.

### Поточна поведінка

```python
df = pd.read_csv(file_path, sep=';', nrows=3)  # Тільки 3 рядки!
client_ids = df['CLIENT_ID'].unique()
if len(client_ids) != 1:
    return MALFORMED
```

### Запропоноване покращення

Додати швидку додаткову перевірку через `usecols=['CLIENT_ID']` (читання лише однієї колонки — швидко на HDD):

```python
# Підтвердити CLIENT_ID константність по ВСЬОМУ файлу
df_check = pd.read_csv(file_path, sep=';', usecols=['CLIENT_ID'])
if df_check['CLIENT_ID'].nunique() != 1:
    return MALFORMED, 'CLIENT_ID not constant in full file'
```

### Вплив на результати

Мінімальний — на нашому датасеті (Харків, 207 файлів) усі CLIENT_ID коректні (підтверджено повним discovery). Цей edge-case теоретичний.

### Обґрунтування "as-is"

Phase A1 все одно повторно валідує `CLIENT_ID` після повного читання (`if int(df_raw['CLIENT_ID'].iloc[0]) != client_id`). Тобто проблемний файл не пройде непоміченим — просто не на discovery, а в A1. Швидкість discovery (3.6 с замість можливих 1+ хв) важливіша.

---

# PHASE A1 — DATA AGGREGATION

## ISSUE-002: `INN_ID` dtype = `float64` через NaN propagation

**Phase:** A1
**Реалізація:** `core/etl.py::fill_gaps`
**Severity:** 🟢 LOW
**Effort to fix:** ⭐
**Status:** ✅ Documented

### Опис проблеми

Після `fill_gaps` колонка `INN_ID` має тип `float64` замість `int64`. Це через те, що під час reindex з'являються тимчасові NaN, які примушують pandas конвертувати int → float.

### Поточна поведінка
```python
INN_ID  dtype: float64    # 177.0, 178.0, ... замість 177, 178
```

### Запропоноване покращення

Після `fill_gaps` явно приводити типи назад:
```python
df_filled["INN_ID"] = df_filled["INN_ID"].astype("int64")
# Або через nullable integer:
df_filled["INN_ID"] = df_filled["INN_ID"].astype("Int64")
```

### Вплив на результати

**Нульовий.** Усі downstream операції (`==`, `isin`, groupby, merge) працюють однаково з int та float. Естетичний нюанс.

### Обґрунтування "as-is"

Канонічний проект так само має float64 INN_ID. Не критично. Якщо у Phase A2/A3 виникнуть проблеми з типами — виправимо локально.

---

## ISSUE-003: NOTSOLD-фільтр з бінарними порогами `[0.20, 0.95]`

**Phase:** A1
**Реалізація:** `pipeline/per_market.py::process_inn`, `config/stockout_params.py`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

NOTSOLD фільтр виключає препарати з NOTSOLD_PERCENT < 20% або > 95%. Логіка:
- `< 20%`: препарат завжди в наявності → немає stockout событий
- `> 95%`: препарат майже не продається → недостатньо даних

**Слабкість:** не враховує **обсяг продажів**. Препарат який продає 1 пачку/тиждень з NOTSOLD=85% має статистично шумний baseline, але проходить фільтр.

### Поточна поведінка

```python
valid_drugs = notsold[
    (notsold['NOTSOLD_PERCENT'] >= 0.20) &
    (notsold['NOTSOLD_PERCENT'] <= 0.95)
]['DRUGS_ID']
```

### Запропоноване покращення

Додати фільтр мінімального обсягу:

```python
# Сума продажів > мінімум для статистичної надійності
total_sales = df_target.groupby('DRUGS_ID')['Q'].sum()
high_volume = total_sales[total_sales >= MIN_TOTAL_SALES].index  # наприклад >= 12 пачок за 156 тижнів

valid_drugs = notsold[
    (notsold['NOTSOLD_PERCENT'] >= 0.20) &
    (notsold['NOTSOLD_PERCENT'] <= 0.95) &
    (notsold['DRUGS_ID'].isin(high_volume))
]['DRUGS_ID']
```

### Вплив на результати

Препарати з низьким обсягом продажів дають **шумний baseline** (`PRE_AVG_Q`), що в Phase A3 призводить до екстремальних `LIFT` ratios. У cross-market агрегації Phase 2 IQR-фільтр частково виключає ці викиди, але краще було б фільтрувати раніше.

### Обґрунтування "as-is"

1. Канонічний проект використовує цю саму логіку.
2. IQR-фільтр у Phase 2 (cross-market) частково компенсує.
3. Жорсткіший фільтр виключив би 30-50% препаратів від подальшого аналізу — втрата статистичної потужності.

---

## ISSUE-004: Memory pressure для файлів 1.5-2 GB

**Phase:** A1
**Реалізація:** `pipeline/per_market.py::process_market`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented (частково мітіговано через `MAX_FILE_SIZE_MB`)

### Опис проблеми

Файли 1.5-2 GB у RAM розгортаються в DataFrame ~5-7 GB (через pandas overhead, string interning, ATC коди тощо). При 6 workers паралельно — пік ~30-35 GB на 32 GB RAM.

### Поточна поведінка
- `MAX_FILE_SIZE_MB = 2048` виключає 2 файли (>2 GB)
- 11 файлів у діапазоні 1.5-2 GB лишаються потенційно ризиковими

### Запропоноване покращення

**Опція 1:** Оптимізація dtypes при `read_csv`:
```python
dtype_map = {
    'CLIENT_ID': 'int32',  # замість int64
    'DRUGS_ID': 'int32',
    'INN_ID': 'int32',
    'PERIOD_ID': 'int32',
}
df_raw = pd.read_csv(file_path, sep=';', dtype=dtype_map, usecols=NEEDED_COLUMNS)
```

**Опція 2:** Ігнорувати непотрібні колонки (`ATC Code (4)`, `ATC Code (5)`):
```python
NEEDED_COLUMNS = [c for c in RAW_REQUIRED_COLUMNS if not c.startswith('ATC')]
df_raw = pd.read_csv(file_path, sep=';', usecols=NEEDED_COLUMNS)
```

**Опція 3:** Smart scheduling в parallel runner — обмежувати кількість workers коли в черзі великі файли.

### Вплив на результати

Без мітигації: ризик OOM на 1-2% запусків (коли 6 workers випадково всі попадають на великі файли). Після мітигації — практично нуль.

### Обґрунтування "as-is"

`MAX_FILE_SIZE_MB=2048` — швидкий захист. Якщо побачимо OOM на 1.5-2 GB файлах при паралельному запуску (Крок 7), застосуємо опції 1+2.

---

## ISSUE-005: ATC коди читаються, але не використовуються (FIXED)

**Phase:** A1
**Реалізація:** `pipeline/per_market.py::process_market_a1` (наша версія — виправлено)
**Severity:** 🟢 LOW
**Effort to fix:** ⭐
**Status:** ✅ **FIXED у нашому проекті** (2026-04-27, перед паралельним запуском)

### Опис проблеми

Колонки `ATC Code (4)` та `ATC Code (5)` читаються разом з усіма іншими, але потім **не використовуються** в жодному кроці нашого pipeline. Споживають RAM та I/O без користі.

### Поточна поведінка
Читаються всі 13 колонок з raw CSV, ATC коди потім просто видаляються після `rename_columns`.

### Запропоноване покращення

```python
# Передавати usecols з виключенням ATC
USEFUL_COLUMNS = [c for c in RAW_REQUIRED_COLUMNS if not c.startswith("ATC Code")]
df_raw = pd.read_csv(file_path, sep=';', usecols=USEFUL_COLUMNS)
```

Економія: ~5-10% RAM, ~5-10% I/O.

### Вплив на результати

Нульовий — просто оптимізація.

### Обґрунтування FIX (виправлено)

Перед паралельним запуском runner-а на 205 ринках вирішили застосувати цю оптимізацію:
- Простий fix (~5 хвилин)
- Економія ~10-15% I/O (важливо для HDD)
- Менше memory pressure (важливо для 6 паралельних workers)
- Жодного впливу на результати — ATC колонки нігде downstream не використовуються

**Зміна:** додано `USEFUL_COLUMNS` константу в `config/column_mapping.py` та `usecols=USEFUL_COLUMNS` в `pd.read_csv()` у Phase A1.

---

# PHASE A2 — STOCKOUT DETECTION

## ISSUE-006: Level 1 (Market Activity) — бінарний поріг `> 0`

**Phase:** A2
**Реалізація:** `core/stockout.py::validate_stockout_event`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

Level 1 валідація вважає ринок INN активним, якщо `MARKET_TOTAL_DRUGS_PACK > 0`. Навіть **1 продана упаковка** в усій INN-групі за весь stockout період проходить.

**Приклад:** INN нормально продає 500 упак/тиждень у конкурентів. Під час нашого 3-тижневого stockout конкуренти продали лише 1 упак. Прохід валідації, але по суті ринок майже мертвий.

### Поточна поведінка

```python
if market_during_inn == 0:
    return False, 'no_market_activity'
# Все інше — passes
```

### Запропоноване покращення

Порівнювати DURING із PRE-baseline (відносний поріг):

```python
# PRE-активність ринку (всі тижні до stockout)
df_inn_pre = df_inn[(df_inn['Date'] >= pre_start) & (df_inn['Date'] <= pre_end)]
market_pre_inn = df_inn_pre['MARKET_TOTAL_DRUGS_PACK'].sum() / pre_weeks  # avg/тиждень

# DURING-активність
market_during_avg = market_during_inn / stockout_weeks

# Якщо DURING < 10% від PRE — вважаємо ринок колапсованим
if market_during_avg < 0.1 * market_pre_inn:
    return False, 'market_collapsed'
```

### Вплив на результати

Без виправлення: проходять події з мертвим ринком → у Phase A3 MARKET_GROWTH буде ≈0 → EXPECTED ≈0 → неадекватно високий LIFT → завищений SHARE_INTERNAL.

### Обґрунтування "as-is"

Phase A3 MARKET_GROWTH природно затухає для мертвих ринків (low EXPECTED → low LIFT). Помилка не **стирається**, а **затухає** через структуру DiD-формули. Не катастрофічно для агрегованих cross-market коефіцієнтів.

---

## ISSUE-007: Level 2 (PRE-period Sales) — бінарний поріг `pre_sales == 0`

**Phase:** A2
**Реалізація:** `core/stockout.py::validate_stockout_event`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

Level 2 пропускає події з `pre_sales > 0`. Навіть якщо це **1 пачка за 4 тижні** PRE — проходить.

**Приклад:** PRE = `[1, 0, 0, 0]` → `pre_sales = 1`, `PRE_AVG_Q = 0.25`. Будь-який пік під час stockout (substitute продав 5 пачок) дасть `LIFT ≈ 5`, `SHARE_INTERNAL ≈ 100%` — штучно завищений результат.

### Поточна поведінка

```python
if pre_weeks < min_pre_weeks or pre_sales == 0:
    return False, 'no_pre_sales'
```

### Запропоноване покращення

Мінімальний обсяг продажів у PRE:

```python
MIN_PRE_TOTAL = 4  # мінімум 4 пачки за 4 тижні (1/тиждень baseline)
if pre_weeks < min_pre_weeks or pre_sales < MIN_PRE_TOTAL:
    return False, 'pre_sales_too_low'
```

### Вплив на результати

Без виправлення: дрібнотоварні препарати з шумним baseline дають екстремальні `LIFT` ratios. У cross-market агрегації IQR-фільтр частково компенсує (виключає викиди), але краще було б фільтрувати на per-event рівні.

### Обґрунтування "as-is"

1. Канонічний проект використовує `pre_sales == 0`.
2. IQR-фільтр у Phase 2 cross-market частково компенсує.
3. Жорсткіший поріг виключив би значущу кількість low-volume drugs (можливо 30-50%).

---

## ISSUE-008: PRE-період 4 тижні — статистично короткий для тижневих даних

**Phase:** A2
**Реалізація:** `config/stockout_params.py::MIN_PRE_PERIOD_WEEKS`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

`MIN_PRE_PERIOD_WEEKS = 4` — нижня межа за статистикою. Для тижневих продажів волатильних препаратів 4 значення недостатньо для надійного baseline.

**Приклад:** препарат коливається [10, 5, 12, 7] PRE → `PRE_AVG = 8.5`, `STD = 3.1`. Розкид 36% від середнього — непостійний baseline.

### Поточна поведінка

```python
MIN_PRE_PERIOD_WEEKS = 4
```

### Запропоноване покращення

Збільшити до 8-13 тижнів (industry standard для sales analytics):

```python
MIN_PRE_PERIOD_WEEKS = 8  # компроміс між baseline noise і event count
```

### Вплив на результати

Trade-off:
- ✅ Менший noise у baseline
- ❌ Втрата подій на початку періоду спостереження (перші 8 тижнів даних без PRE)
- ❌ Старші PRE-дані можуть включати сезонні зрушення (особливо для 13 тижнів = ~3 місяці)

### Обґрунтування "as-is"

4 тижні — компроміс канонічного проекту. Для нашого 156-тижневого датасету (3 роки) збільшення до 8 не критичне за втратою подій, але змінить методологічну порівнянність із канонічним проектом.

---

## ISSUE-009: PRE_AVG_Q розраховується через mean — чутливий до викидів

**Phase:** A2
**Реалізація:** `core/stockout.py::validate_stockout_event` (поле `pre_avg_q`)
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐
**Status:** ✅ Documented

### Опис проблеми

```python
details['pre_avg_q'] = pre_sales / pre_weeks
```

Це арифметичне середнє. Чутливе до викидів.

**Приклад:** PRE = [1, 0, 0, 50] (одна абнормальна закупка опт-клієнтом). 
- `pre_sales = 51`, `pre_weeks = 4`
- `PRE_AVG_Q = 12.75` ← сильно завищене
- Реальний "типовий" рівень = 0-1 пачка/тиждень
- Медіана була б = 0.5 (значно ближче до типу)

EXPECTED = `PRE_AVG_Q × MARKET_GROWTH = 12.75 × ...` сильно перевищує реальну очікувану продажу → LIFT занижений → SHARE_INTERNAL занижений.

### Поточна поведінка

```python
pre_avg_q = pre_sales / pre_weeks  # arithmetic mean
```

### Запропоноване покращення

Робастна оцінка через медіану або trimmed mean:

```python
df_pre_q = df_pre['Q']
pre_median_q = df_pre_q.median()
# або 25%-trimmed mean: видалити по 25% найменших і найбільших значень
```

Якщо PRE = [1, 0, 0, 50]:
- Median = 0.5 (значно реалістичніше)
- Trimmed mean (25%) = mean([0, 1]) = 0.5

### Вплив на результати

Препарати з оптовими епізодичними покупками (не роздрібний попит) дають завищений `PRE_AVG_Q` → занижений LIFT → занижений `SHARE_INTERNAL`. Це систематичний bias для певної категорії препаратів (наприклад, рецептурні + B2B канал).

### Обґрунтування "as-is"

1. Канонічний проект використовує mean.
2. У Phase 2 cross-market IQR-фільтр виключає extremaльні значення SHARE_INTERNAL.
3. Перехід на median вимагав би повторної валідації методології (можливо зміна порогів, новий бізнес-аналіз).

---

## ISSUE-010: Level 3 (Competitors Availability) — бінарний поріг

**Phase:** A2
**Реалізація:** `core/stockout.py::validate_stockout_event`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

Level 3 проходить якщо `competitors_sales > 0` — навіть якщо лише 1 конкурент із 10 продав 1 упаковку.

**Сценарій:** 10 конкурентів, 9 не мають препарату, 1 продав 1 упак. Технічно "альтернатива існує", але реально:
- Покупець із нашого району може й не дійти до того одного конкурента
- LOST_SALES буде штучно близько до 0
- SHARE_INTERNAL завищений

### Поточна поведінка

```python
if competitors_sales == 0:
    return False, 'no_competitors'
```

### Запропоноване покращення

Мінімум K активних конкурентів:

```python
# (Потребує збереження PHARM_ID-розбивки в Phase A1, зараз ми агрегуємо)
n_active_competitors = (
    df_drug_during.groupby('PHARM_ID')['Q'].sum() > 0
).sum()

MIN_ACTIVE_COMPETITORS = 2
if n_active_competitors < MIN_ACTIVE_COMPETITORS:
    return False, 'too_few_competitors'
```

### Вплив на результати

Систематичний bias до завищення `SHARE_INTERNAL` для drugs зі слабкою конкурентною дистрибуцією.

### Обґрунтування "as-is"

1. Канонічний проект приймає `> 0`.
2. Архітектурне обмеження: ми зараз зберігаємо `MARKET_TOTAL_DRUGS_PACK` (sum по конкурентах), не PHARM_ID-розбивку. Виправлення вимагало б переглянути Phase A1 output структуру.
3. Ефект для презентаційного демо незначний.

---

## ISSUE-011: Level 3 не порівнюється з PRE-конкурентами

**Phase:** A2
**Реалізація:** `core/stockout.py::validate_stockout_event`
**Severity:** 🟡 MEDIUM
**Effort to fix:** ⭐⭐
**Status:** ✅ Documented

### Опис проблеми

Level 3 перевіряє лише `competitors_sales > 0` під час stockout. Не порівнюється з рівнем PRE.

**Сценарій галузевого спаду:** конкуренти продавали 100 упак/тиждень PRE, потім 1 упак/тиждень DURING.
- Технічно проходить (>0)
- Реально це **загальногалузевий стокаут**, а не фокусний у нашій аптеці
- DiD аналіз неадекватний: ми міряємо stockout окремої аптеки, а тут стокаут індустрії

### Поточна поведінка

```python
if competitors_sales == 0:
    return False, 'no_competitors'
```

### Запропоноване покращення

Відносний поріг проти PRE-рівня:

```python
df_drug_pre = df_drug[(df_drug['Date'] >= pre_start) & (df_drug['Date'] <= pre_end)]
competitors_pre = df_drug_pre['MARKET_TOTAL_DRUGS_PACK'].sum() / pre_weeks  # avg/тиждень
competitors_during_avg = competitors_sales / stockout_weeks

if competitors_during_avg < 0.2 * competitors_pre:  # < 20% від PRE
    return False, 'industry_wide_stockout'
```

### Вплив на результати

Невідфільтровані події загальногалузевого стокаута дають викривлені SHARE метрики.

### Обґрунтування "as-is"

1. Канонічний так не робить.
2. Phase A3 MARKET_GROWTH природно затухає при колапсі ринку (similar до ISSUE-006 для Level 1).
3. У cross-market агрегації Phase 2 викиди частково виключаються через IQR.

---

## ISSUE-012: POST-period валідація відкладена на Phase A3

**Phase:** A2 / A3 (cross-cutting)
**Реалізація:** `core/stockout.py` (відсутня перевірка) + `core/did.py` (буде у A3)
**Severity:** 🟢 LOW
**Effort to fix:** ⭐
**Status:** ✅ Documented (architectural choice)

### Опис проблеми

Stockout події валідуються тільки за PRE-критеріями + market activity. **POST-validation** (чи відновились продажі після stockout) робиться лише у Phase A3 при розрахунку DiD.

**Ефект:** події з невалідним POST зберігаються у `stockout_events.parquet`, але потім відкидаються у Phase A3. Створює "мертві" події в проміжному файлі.

### Поточна поведінка

Phase A2: 3-level validation, без POST.
Phase A3: окремо `validate_post_period(...)` під час DiD.

### Запропоноване покращення

Об'єднати POST-validation у Phase A2:

```python
# Додати 4-й рівень у validate_stockout_event:
post_start, post_end, post_weeks, post_status = define_post_period(...)
if post_status != 'valid':
    return False, f'no_post_recovery_{post_status}'
```

### Вплив на результати

Архітектурний нюанс — фінальні цифри коректні. Лише трохи більше зайвих записів у проміжному файлі.

### Обґрунтування "as-is"

Канонічна архітектура поділяє відповідальність: A2 — pure stockout detection, A3 — DiD-related (включно з POST). Логіка чиста, не змішується.

---

# PHASE A3 — DiD ANALYSIS

## ISSUE-013: LOST_SALES математично некоректний у канонічному коді (FIXED)

**Phase:** A3
**Реалізація:** `core/did.py::calculate_did_for_event` (наша версія — виправлено)
**Канонічний:** `cross_pharm_market_analysis/exec_scripts/01_did_processing/02_03_did_analysis.py:437-441`
**Severity:** 🔴 HIGH (у канонічному коді)
**Effort to fix:** ⭐ (one-line зміна)
**Status:** ✅ **FIXED у нашому проекті** (свідомий divergence від канонічного)

### Опис проблеми

У канонічному `02_03_did_analysis.py` LOST_SALES розраховується inline (рядки 437-441) **некоректно**:

```python
# Канонічний (BUG):
market_total_pre = df_drug_pre['MARKET_TOTAL_DRUGS_PACK'].sum()  # ← КОНКУРЕНТИ ОНLY
target_pre       = df_drug_pre['Q'].sum()                         # ← target's Q
comp_pre = max(0, market_total_pre - target_pre)                  # ← ПОДВІЙНЕ ВІДНІМАННЯ!
```

### Корінь проблеми

`MARKET_TOTAL_DRUGS_PACK` в `aggregated.parquet` — це сума **тільки по конкурентах**, бо в Phase A1 ми викликаємо:
```python
market_totals = calculate_market_totals(df_competitors, ...)  # ← df_competitors only
```

Тобто `market_total_pre` **уже виключає target**. Віднімати `target_pre` ще раз — некоректно.

Підтвердження що це bug, не задумка: у тому ж канонічному `did_utils.py::calculate_lost_sales` цей самий розрахунок реалізовано **правильно**:

```python
# Канонічний did_utils.py — ПРАВИЛЬНА версія (не використовується в 02_03!):
df_pre = df_drug[(df_drug[date_col] >= pre_start) & ...]
comp_pre = df_pre[quantity_col].sum()  # ← БЕЗ віднімання target_pre
```

Тобто канонічний має **дві версії** одного розрахунку: правильну в `did_utils.py` (не використовується) і помилкову inline в `02_03_did_analysis.py` (фактично виконується).

### Систематичний bias у канонічному

Внаслідок подвійного віднімання:

```
canonical_comp_pre   = market_total_pre - target_pre     # занижено на target_pre
canonical_expected   = canonical_comp_pre × MARKET_GROWTH # занижено
canonical_lost_sales = max(0, comp_during - canonical_expected) # завищено

→ canonical_SHARE_LOST     завищено
→ canonical_SHARE_INTERNAL занижено
```

Тобто **усі канонічні SHARE_INTERNAL значення систематично занижені**, що поширюється на всі downstream метрики (медіану, валідні препарати після фільтрації, тощо).

### Наша поточна поведінка (FIXED)

```python
# core/did.py — наша виправлена версія:
df_drug_pre = df_target_drug[(df_target_drug['Date'] >= pre_start) & ...]
comp_pre    = df_drug_pre['MARKET_TOTAL_DRUGS_PACK'].sum()  # ← використовуємо напряму
```

Без віднімання target_pre. Математично коректно, узгоджується з логікою `did_utils.calculate_lost_sales`.

### Вплив на результати

**Замовник (the pharmacy chain)** не порівнюватиме з канонічним проектом → нам важлива математична точність, а не порівнянність. Тому FIX виправдано.

**Очікувана різниця між нашими і канонічними результатами:**
- SHARE_INTERNAL у нас буде **дещо вище** для більшості подій
- На скільки саме — залежить від співвідношення `target_pre / market_total_pre`
- У ринках де target має значну частку (great-volume drugs у власній аптеці) — різниця буде помітна
- У ринках де target має малу частку — різниця мала

### Рекомендації для майбутнього

1. **Якщо потрібна порівнянність** з канонічним — повернутись до Опції A (з відніманням), або
2. **Виправити канонічний** проект (обговорити з Radyslav Lomanov як автором)
3. У продакшені: додати валідацію через permutation tests або bootstrap CI на per-event LIFT

### Обґрунтування "FIXED" (а не "as-is")

Користувач прийняв рішення **Опція B (fix)** на основі:
1. Демо для the pharmacy chainа — порівнянність з канонічним не потрібна
2. Математична точність важливіша за послідовність із попередніми результатами
3. One-line fix — низький ризик

---

# PHASE A4, B, C — ще не розглянуто

(Цей розділ заповнюватиметься в міру реалізації наступних кроків.)

---

# ЗАГАЛЬНА ТЕХНІЧНА СТРАТЕГІЯ

## ISSUE-014: COEF_1 = median не валідний для MULTIMODAL препаратів (FIXED)

**Phase:** B (cross-market aggregation)
**Реалізація:** `pipeline/cross_market.py::aggregate_cross_market` (наша версія — виправлено)
**Канонічний:** аналогічна логіка у канонічному (median як головна метрика)
**Severity:** 🔴 HIGH (для бізнес-інтерпретації)
**Effort to fix:** ⭐ (заміна формули + додавання 3 декомпозиційних колонок)
**Status:** ✅ **FIXED у нашому проекті** (Крок 13, 2026-04-28)

### Опис проблеми

Канонічна метрика COEF_1 = `median(SHARE_INTERNAL after IQR filter)` — статистично репрезентативна тільки для UNIMODAL розподілів. Для MULTIMODAL (8% препаратів у нашому датасеті, 508/6265) медіана **приховує бімодальність** і дає введення в оману.

### Конкретний приклад: DRUGS_ID=1578 (ДИКЛОКАИН)

- 30 ринків з stockout-подіями
- У 16/30 ринків (53.3%) — клієнт повністю йшов з аптеки (SHARE=0)
- У 14/30 ринків (46.7%) — клієнт залишався і брав substitute (середній SHARE=0.731)
- **median = 0.0** → інтерпретація «препарат повністю унікальний»
- Реальність: у 47% ринків substitution є, на 73% обсягу

Бізнес отримував число COEF_1=0.0 і висновок «препарат критичний» — насправді препарат **частково замінюваний** у половині ринків.

### Виправлення

`COEF_1` тепер обчислюється як `mean(SHARE_INTERNAL after IQR)`. Додатково в drug_coefficients.csv додано 3 декомпозиційні колонки:

- `COVERAGE_PCT` = % ринків з SHARE > 0
- `CONDITIONAL_RETENTION` = mean(SHARE | SHARE > 0)
- `MARKETS_WITH_SUB` = абсолютна кількість таких ринків

Інваріант: **COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION** (математично точно).

Для UNIMODAL препаратів зміна мінімальна (mean ≈ median). Для MULTIMODAL — кардинальна:
- DRUGS_ID=1578: COEF_1 0.000 → **0.341** (mean), COVERAGE=0.467, CONDITIONAL=0.731.

### Impact

Для 508 MULTIMODAL препаратів та ~640 UNIMODAL зі скошеним розподілом (як КОРНЕРЕГЕЛЬ: median 0.025, mean 0.059) — отримуємо чесніше число COEF_1 + 3 додаткові метрики, які роблять видимою бімодальність.

---

## ISSUE-015: NFC1 hardcoded список + помилкова ORAL_GROUP (FIXED)

**Phase:** A3 (DiD substitute identification)
**Реалізація:** `core/nfc.py` (наша версія — повністю переписана)
**Канонічний:** `cross_pharm_market_analysis/project_core/did_config/nfc_compatibility.py`
**Severity:** 🟡 MEDIUM (методологічно важлива)
**Effort to fix:** ⭐⭐ (динамічний registry + перерозбиття групи + warning логіка)
**Status:** ✅ **FIXED у нашому проекті** (Крок 14, 2026-04-28)

### Опис двох пов'язаних проблем

**А) Hardcoded NFC1 список:**

Канонічний `nfc_compatibility.py` містить **9 hardcoded** NFC1-категорій — точно ті, що зустрілися у канонічному датасеті. Коли pipeline запускається на новому датасеті (як наш — the pharmacy chain), категорії, яких НЕМАЄ у канонічному, **ігноруються мовчки**:

- `is_compatible(невідома, x)` поверне False для будь-якого x ≠ невідома (бо невідома немає в ORAL_GROUP).
- Препарат з невідомою NFC1 фактично трактується як standalone — це коректний default, але без жодного логування. Аналітик не побачить, що в датасеті є непокриті категорії.

У нашому датасеті 16 NFC1 категорій vs 9 канонічних — 7 «нових» категорій, серед яких:
- `Назальные системные`, `Отологические`, `Парентеральные длительно действующие`, `Местные назальные`, `Вагинальные`, `Для введения в легкие`, `Пероральные местного действия`.

**Б) Помилкова ORAL_GROUP:**

Канонічна група об'єднувала 3 форми як взаємозамінні:
```python
ORAL_GROUP = [
    "Пероральные твердые обычные",
    "Пероральные жидкие обычные",          ← включена помилково
    "Пероральные твердые длительно действующие",
]
```

Клінічно це невірно: клієнт, що бере **сироп** (ремедії дітям, людям з труднощами ковтання), **не еквівалентно** перейде на тверді таблетки. Це різні клієнтські сценарії з різними тригерами купівлі.

### Виправлення

**А) Dynamic master registry:**
- `data/master/nfc1_config.json` — JSON-довідник, що **накопичується** між запусками.
- `pipeline/discover_markets.py` сканує `NFC Code (1)` у всіх raw CSV → додає нові категорії (накопичувано, ніколи не видаляє історичні).
- `core/nfc.py::is_compatible()` тепер працює через цей JSON.
- Невідома категорія → standalone (exact-match only) **+ warning у лог** (один раз на форму).

**Б) Перерозбиття ORAL_GROUP:**
- Нова група `ORAL_SOLID_RETARD`: тільки `Пероральные твердые обычные` ↔ `Пероральные твердые длительно действующие`.
- `Пероральные жидкие обычные` тепер замінюються тільки самі на себе (як інші стандартні форми).

### Impact

- Усі майбутні датасети автоматично отримають правильну NFC compatibility (registry самоонов лювальний).
- Substitution для tablet-препаратів більше не «розбавлена» рідкими формами → точніший `substitute_shares`.
- Для нашого датасету ефект очікуваний: для tablet-препаратів зменшиться кількість substitutes (зникнуть liquid-форми як кандидати), збільшиться концентрація `SUBSTITUTE_SHARE` на справжніх tablet-замінниках.

---

## ISSUE-016: «Фантомні» substitutes у фінальному файлі (FIXED)

**Phase:** C (final export — `pipeline/final_export.py::build_substitute_shares`)
**Severity:** 🟡 MEDIUM (косметично-методологічна — бізнес-користувач плутається)
**Effort to fix:** ⭐ (один-рядковий фільтр + лог)
**Status:** ✅ **FIXED у нашому проекті** (Крок 16, 2026-05-01)

### Опис проблеми

При формуванні `substitute_shares.csv/.xlsx` у Phase C виявлено невелику
кількість «фантомних» рядків:
- `SUBSTITUTE_SHARE = 0.000000` (округлення до точно нуля)
- але пара (DRUGS_ID → SUBSTITUTE_DRUG_ID) формально присутня у файлі.

У повному датасеті: **20 з 134 101 рядків** (≈ 0.015 %).

### Корінь проблеми

Phase A4 / Phase C виконують LIFT-зважену агрегацію substitute pairs:
1. У `substitute_pairs.parquet` (Phase A3) пара потрапляє, якщо substitute мав
   `LIFT > 0` хоча б у одному ринку.
2. Phase C агрегує LIFT по всіх ринках і нормалізує `SUBSTITUTE_SHARE` до 1.0
   на цільовий препарат.
3. Якщо інші substitutes отримали більшу частку, а конкретний substitute
   зустрічався тільки в малому ринку з мізерним LIFT — після крос-маркет
   агрегації та `round(6)` його частка стає рівно `0.000000`.

Тобто пара формально валідна (модель її бачила), але ефективна вага = 0 — для
бізнес-користувача це **не substitute**.

### Виявлення

Виявлено при ad-hoc підготовці файлу для аналітика
(`_optional_calculations/top_1k_reliability_sales_volume/`). У вхідному файлі
від PowerBI також були ті ж самі 16 нулів — підтверджено, що це не баг експорту,
а властивість самої методології.

### Виправлення

У `pipeline/final_export.py::build_substitute_shares`, після обчислення
`SUBSTITUTE_SHARE` (Step 4) і **до** призначення `SUBSTITUTE_RANK` (Step 5),
додано фільтр:

```python
# Step 4b: Видалення «фантомних» substitutes (SHARE = 0 після нормалізації)
n_before_phantom_filter = len(pair_agg)
pair_agg = pair_agg[pair_agg["SUBSTITUTE_SHARE"] > 0].copy()
n_phantom_removed = n_before_phantom_filter - len(pair_agg)
```

### Дизайн-патерн: «broad model, narrow export»

Свідоме рішення — фільтр діє **тільки на фінальний експорт**:
- `data/intermediate/01_per_market/{cid}/substitute_pairs.parquet` (Phase A3)
  — повна видимість для debugging/audit.
- `data/intermediate/01_per_market/{cid}/substitute_shares.parquet` (Phase A4)
  — повна видимість.
- `data/intermediate/02_cross_market/drug_statistics.parquet` (Phase B) —
  без змін (стосується drug_coefficients).
- `results/final/substitute_shares.csv/.xlsx` (Phase C) — **тут фільтр
  застосовується**.

Цей патерн (відомий також як «full-fidelity model + curated export») —
стандарт у data engineering, де модель має зберігати повну прозорість для
розслідувань, а production-output чистий від артефактів агрегації.

### Impact

- 134 101 → 134 081 пара у фінальному файлі (-20 фантомів).
- Sum-to-1 інваріант продовжує виконуватись (max diff 0.000011 → 0.000011).
- RANK тепер починається з 1 для **кожного** препарату, бо фільтр діє ДО
  ranking (інакше фантоми могли б отримати rank 14, 15, ... і випадати
  після фільтра, спотворюючи послідовність).
- 16 інваріантів валідації — усі PASSED.

---

## Чому залишаємо канонічну логіку 1-в-1 для презентації

1. **Презентаційний демо проект** — пріоритет порівнянність із канонічним
2. **Канонічна методологія валідована** на 99 ринках (47% препаратів пройшли Scenario A фільтр з RELIABILITY HIGH/MEDIUM)
3. **Внесення покращень** = окремий проект з валідацією, не швидкі зміни
4. **Ризик пере-фільтрування:** жорсткіші пороги → менше валідних подій → ширші CI → менше препаратів у фінальних файлах

## Коли варто переглядати

| Тригер | Дія |
|--------|-----|
| Замовник запитує про методологічні удосконалення | Розглянути ISSUE з 🟡 MEDIUM severity |
| Зростання обсягу даних до 1000+ ринків | ISSUE-004 (memory) стає критичним |
| Виявлення бізнес-аномалій у результатах | Розглянути pre_avg via median (ISSUE-009) |
| Окремий продакшен-проект (не демо) | Систематичний перегляд усіх 🟡 + 🔴 |

---

## ЛІЧИЛЬНИК ISSUE

| Severity | Кількість |
|----------|-----------|
| 🟢 LOW | 4 |
| 🟡 MEDIUM | 7 |
| 🔴 HIGH | 1 (✅ FIXED) |
| **Всього** | **12** |

| Effort | Кількість |
|--------|-----------|
| ⭐ | 8 |
| ⭐⭐ | 7 |
| ⭐⭐⭐ | 0 |

| Status | Кількість |
|--------|-----------|
| ✅ Documented (as-is) | 10 |
| ✅ FIXED in our project | 5 (ISSUE-005, ISSUE-013, ISSUE-014, ISSUE-015, ISSUE-016) |

## CHANGELOG

| Дата | Версія | Зміни |
|------|--------|-------|
| 2026-04-27 | 1.0 | Створено документ; ISSUE-001 (A0); ISSUE-002...005 (A1); ISSUE-006...012 (A2) |
| 2026-04-27 | 1.1 | ISSUE-013 (A3): LOST_SALES double-subtract bug — FIXED in our impl |
| 2026-04-28 | 1.2 | ISSUE-014 (Phase B): COEF_1 = median не валідний для MULTIMODAL — FIXED (mean + COVERAGE_PCT/CONDITIONAL_RETENTION). ISSUE-015 (Phase A3 NFC compatibility): hardcoded NFC1 список + помилка ORAL_GROUP (рідкі ↔ тверді не клінічно еквівалентні) — FIXED (dynamic master registry + ORAL_SOLID_RETARD без рідких). |
| 2026-05-01 | 1.3 | ISSUE-016 (Phase C): «фантомні» substitutes з SHARE=0 у фінальному файлі (20 з 134 101) — FIXED (фільтр SHARE > 0 у `build_substitute_shares` між Steps 4 і 5; intermediate parquet зберігає повну видимість — pattern «broad model, narrow export»). |
