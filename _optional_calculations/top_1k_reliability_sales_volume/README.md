# top_1k_reliability_sales_volume

Ad-hoc розрахунок: відбір препаратів **для подальшого аналізу аналітиком у Power BI**
за подвійним фільтром:
1. **Статистична надійність** COEF_1 (RELIABILITY_SCORE).
2. **Бізнес-значущість** через обсяг продажів (Pareto coverage).

Результат — два xlsx-файли (drug_coefficients + substitute_shares), формат
яких **повністю ідентичний** вхідним PowerBI-файлам, тобто аналітик може
просто замінити вхідні файли на ці відфільтровані без жодних змін у Power BI.


---

## ⚡ Порядок запуску

Скрипти запускаються **послідовно** з кореня проекту `drug_substitution_engine/`.
Використовуй будь-який Python-інтерпретатор з встановленим `requirements.txt`
(нижче — приклад для локального venv `.venv\`):

```bash
# Крок 1: основний фільтр (drug_coefficients)
.venv\Scripts\python.exe _optional_calculations/top_1k_reliability_sales_volume/run_filter.py

# Крок 2: subset substitute_shares (для тих DRUGS_ID, що пройшли крок 1)
.venv\Scripts\python.exe _optional_calculations/top_1k_reliability_sales_volume/run_substitutes_subset.py
```

> Linux/macOS: заміни `.venv\Scripts\python.exe` на `.venv/bin/python`.

Параметри відбору налаштовуються в `config.py` — без модифікації самих скриптів.


---

## Контекст і мотивація

Після передання v2.1-результатів (6 264 препарати, 134 101 substitute-пар) виникла
потреба надати аналітику **обмежену вибірку** препаратів для глибшого ручного
аналізу та використання у Power BI. Повний список занадто великий для практичного
огляду.

Просте сортування за `RELIABILITY_SCORE DESC` дає у топі препарати з `COEF_1=0.0`
(всі ринки показали SHARE=0 → формально найстабільніша статистика, але тривіально
критичні препарати). Тому використовується **подвійний фільтр**, де:
- сторону «надійності» забезпечує мінімальний поріг RELIABILITY_SCORE,
- сторону «бізнес-значущості» забезпечує Pareto coverage за обсягом продажів.


---

## Методологія відбору (run_filter.py)

### Етапи фільтрації

```
ВХІД: drug_coefficients_power_bi_sales_volume.xlsx (5 803 препарати)
  │
  ▼  [1] LEFT JOIN з results/final/drug_coefficients.csv (v2.1)
  │      → отримуємо RELIABILITY_SCORE для кожного DRUGS_ID
  │
  ▼  [2] DROPNA (на випадок orphans без RELIABILITY_SCORE)
  │
  ▼  [3] FILTER: MIN_RELIABILITY_SCORE ≤ RELIABILITY_SCORE ≤ MAX_RELIABILITY_SCORE
  │      → за замовчуванням MIN=0.70 (надійні препарати)
  │
  ▼  [4] SORT: за «Обсяг (UAH)» DESC
  │
  ▼  [5] PARETO CUT: беремо мінімум препаратів, що сумарно покривають
  │      PARETO_COVERAGE_TARGET від обсягу (за замовчуванням 0.80)
  │
ВИХІД: drug_coefficients_power_bi_sales_volume_filtered.xlsx
       (~900 препаратів, що дають 80% обсягу та надійні статистично)
```

### 1. Чому MIN_RELIABILITY_SCORE = 0.70

`RELIABILITY_SCORE` — композитний показник 0..1 з пайплайну (Phase B), що
враховує:
- **Stability** = 1 − CV (нормований розкид COEF_1 по ринках),
- **Sample size** = log10-сатурація на 150 ринках,
- **Modality penalty** = 0.85 для MULTIMODAL.

Поріг **0.70** відсіює препарати з:
- помірним або сильним розкидом по ринках (CV > 0.30),
- малою кількістю ринків (<25),
- бімодальним розподілом з шумом.

У нашому датасеті 5 803 препаратів **2 448 (≈42%) пройшли цей фільтр**.
Налаштування — у `config.py: MIN_RELIABILITY_SCORE`.


### 2. Чому Pareto coverage 80% (правило 80/20)

Дані обсягу продажів у фарма-роздробі — класичний long-tail розподіл. У
поточному датасеті:
- TOP-1 / Median  ≈  41×   (top-1 у 41 раз більший за медіанний препарат)
- TOP-1 / Min     ≈ 40 000×
*(абсолютні UAH-обсяги — клієнтські; не публікуються)*

Фіксовані пороги (`top-1000`, `% від ТОП-1`) не стійкі до зміни структури
датасету. **Pareto coverage** математично обґрунтований і самозбалансований:
> «Беремо мінімальну кількість препаратів, що сумарно дають X% обороту мережі.»

Класичне правило 80/20 (Pareto principle, 1906) — золотий стандарт у роздрібній
фармацевтиці для виділення «значущого» сегмента.

У нашому датасеті після RELIABILITY-фільтра 2 448 препаратів:
- 70% → 639 препаратів
- 75% → 758
- **80% → 900** ⭐ (за замовчуванням)
- 85% → 1 072
- 90% → 1 300

Налаштування — у `config.py: PARETO_COVERAGE_TARGET`.


### 3. Альтернативи, які розглядалися й відхилені

| Метод | Чому НЕ використовуємо |
|-------|------------------------|
| Фіксований `top-N` (наприклад N=1000) | Не самобалансується при зміні датасету; не математично обґрунтовано |
| `% від ТОП-1` | Чутливо до викидів — один аномальний препарат-лідер змінює поріг |
| `% від mean(ТОП-K)` | Робастніше за «% від ТОП-1», але вимагає ще одного параметра K |
| Log10 + std break point | Математично коректно для long-tail, але важко пояснити замовнику |


---

## Методологія subset substitutes (run_substitutes_subset.py)

Простіша задача:

```
ВХІД: substitute_shares_power_bi.xlsx (85 503 пар, 5 405 source DRUGS_ID)
  │
  ▼  [1] Завантажити список 900 DRUGS_ID, що пройшли run_filter.py
  │
  ▼  [2] FILTER: SUBSTITUTE_SHARES, де DRUGS_ID ∈ {ці 900}
  │
  ▼  [3] Збереження dtypes + sheet name точно як вхідний файл
  │
ВИХІД: substitute_shares_power_bi_filtered.xlsx (22 736 пар, 798 source drugs)
```

З 900 препаратів **798 (≈89%)** мають substitute pairs у датасеті; решта
102 — це препарати без виявлених замінників (нормально для пайплайну).

Розподіл substitutes per drug у виборці:
- min=1, median=22, max=97, mean=28.5


---

## Параметри (config.py)

| Параметр | Значення default | Опис |
|----------|------------------|------|
| `MIN_RELIABILITY_SCORE` | 0.70 | Мін. поріг надійності COEF_1 (0..1) |
| `MAX_RELIABILITY_SCORE` | 1.0  | Макс. поріг (1.0 = без обмеження) |
| `PARETO_COVERAGE_TARGET` | 0.80 | Цільове % покриття обороту (0..1] |
| `TOP_N` | None | Жорстке обмеження кількості (ігнорується при PARETO=задано) |
| `SORT_BY_COLUMN` | "Обсяг (UAH)" | Колонка для сортування DESC |
| `INCLUDE_RELIABILITY_IN_OUTPUT` | False | True → 17 колонок (для аналізу), False → 16 (для Power BI) |


---

## Структура папки

```
top_1k_reliability_sales_volume/
├── README.md                           ← цей файл
├── config.py                           ← параметри відбору
├── run_filter.py                       ← Крок 1: drug_coefficients filter
├── run_substitutes_subset.py           ← Крок 2: substitute_shares subset
├── inputs/
│   ├── drug_coefficients_power_bi_sales_volume.xlsx  ← від замовника
│   └── substitute_shares_power_bi.xlsx               ← від замовника
├── outputs/
│   ├── drug_coefficients_power_bi_sales_volume_filtered.xlsx  ← Output Кроку 1
│   ├── substitute_shares_power_bi_filtered.xlsx               ← Output Кроку 2
│   └── statistics.txt                                          ← звіт run_filter.py
└── logs/
    ├── run_YYYYMMDD_HHMMSS.log                ← логи run_filter.py
    └── run_substitutes_YYYYMMDD_HHMMSS.log    ← логи run_substitutes_subset.py
```


---

## Залежності

### Read-only
- `inputs/drug_coefficients_power_bi_sales_volume.xlsx` — від замовника (5 803 × 16).
- `inputs/substitute_shares_power_bi.xlsx` — від замовника (85 503 × 8).
- `results/final/drug_coefficients.csv` — наш v2.1, джерело RELIABILITY_SCORE.

### Не зачіпає
- `pipeline/`, `core/`, `config/` — продакшн-пайплайн НЕ модифікується.
- `results/final/` — оригінальні фінальні файли НЕ змінюються.
- `data/`, `reports/`, `docs/` — не торкаються.


---

## Поточні цифри (run від 2026-05-01)

```
ВХІД (drug_coefficients):       5 803 препарати
  → після RELIABILITY ≥ 0.70:   2 448 (-3 355)
  → після Pareto 80%:             900 (-1 548)  актуальне покриття: 80.03 %
                                                (абсолютний оборот — клієнтський,
                                                 не публікується)

ВХІД (substitute_shares):       134 081 пар, 5 857 unique sources
                                (results/final/substitute_shares.csv —
                                 продакшн-файл після ISSUE-016 fix)
  → після subset:                22 730 пар, 798 unique sources
                                 (102 препарати з 900 не мають substitutes)
```


---

## Як змінити поведінку

| Хочу | Що міняти у config.py |
|------|------------------------|
| Більше/менше препаратів через надійність | `MIN_RELIABILITY_SCORE` (0.6 → ~3 213, 0.85 → ~1 085) |
| Більше/менше за Pareto | `PARETO_COVERAGE_TARGET` (0.75 → 758, 0.85 → 1 072) |
| Зафіксувати конкретну кількість | `PARETO_COVERAGE_TARGET = None`, `TOP_N = 500` |
| Розширити RELIABILITY поряд з SCORE для аналізу | `INCLUDE_RELIABILITY_IN_OUTPUT = True` |

Після зміни — **перезапустити обидва скрипти** (Крок 1 → Крок 2).


---

## Етапність роботи (хронологія рішень)

1. **Початкова постановка:** замовник просить top-1000 препаратів за подвійним
   фільтром (надійність × обсяг продажів).

2. **Перша ітерація — фіксований top-1000:** відхилено як неструктуровану логіку
   («чому саме 1000, а не 500 чи 2000?»).

3. **Друга ітерація — RELIABILITY_SCORE ≥ 0.70:** математично обґрунтовано
   (canonical-style CV-based threshold). 5 803 → 2 448.

4. **Третя ітерація — Pareto 80% over volume:** замість фіксованого top-N —
   класичне правило 80/20 з фарма-роздробу. 2 448 → 900.

5. **Четверта ітерація — формат drop-in для Power BI:** збережено dtypes,
   sheet name "Drug Coefficients", без RELIABILITY_SCORE у фінальному файлі.

6. **П'ята ітерація — subset substitute_shares:** окремий скрипт фільтрує
   substitute_shares до 900 source DRUGS_ID. 85 503 → 22 736 пар.

7. **Шоста ітерація — ISSUE-016 (phantom substitutes):** при перевірці виявлено,
   що в обох файлах (від аналітика та нашому продакшн) присутні рядки з
   `SUBSTITUTE_SHARE = 0.000000` — формально substitute, але після
   cross-market агрегації + округлення вага = 0. Це не баг файлу від
   аналітика, а методологічна неточність самого продакшн-пайплайну.
   **Виправлено в продакшн-пайплайні** (`pipeline/final_export.py`) — додано
   фільтр SHARE > 0 у Phase C. Pattern «broad model, narrow export»:
   intermediate parquet зберігає повну видимість, фільтр діє тільки на
   експорт. Ad-hoc input замінено на чистий `results/final/substitute_shares.csv`
   замість файлу від аналітика. Результат: 22 736 → **22 730 пар** (0 phantoms).
   Деталі — у `docs/_methods_issues.md::ISSUE-016` і `docs/LOGS.md::Крок 16`.


---

## Залежність від продакшн-пайплайну

Цей розрахунок:
- **Читає** `results/final/drug_coefficients.csv` (продакшн-вихід v2.1).
- **Не змінює** жодного файлу пайплайну.
- **Не входить** до `run.bat` (продакшн-launcher).
- Запускається **окремо**, на запит, із цієї папки.

При оновленні продакшн-пайплайну (новий датасет, нова версія методології)
просто перезапустити обидва скрипти — вони використають новий v2 файл як
джерело.


---

## Версія

- **v1** (2026-05-01) — RELIABILITY ≥ 0.70 + Pareto 80% + subset substitutes.
