# CLAUDE BRIEFING — drug_substitution_engine

## Повний брифінг для AI-асистента (Claude Code) при підключенні до проекту

> **Підготовлено:** 2026-05-08
> **Призначення:** Цей документ забезпечує повний контекст для продовження
> роботи на новому ПК або у новому сеансі. Прочитай його повністю перед
> початком будь-яких дій.

---

## 1. СУТЬ ПРОЕКТУ

`drug_substitution_engine` — обчислювальний модуль (engine) для аналізу
коефіцієнтів субституції фармацевтичних препаратів на базі даних роздрібної
мережі аптек. Цей **engine — generic-шаблон**: він приймає на вхід стандартний
формат сирих CSV від постачальника фарма-даних і видає 4 фінальні файли для
Power BI, незалежно від того, для якого замовника обробляються дані.

**Бізнес-питання:** Якщо препарат тимчасово відсутній на полиці, наскільки
часто клієнт залишається в цій же аптеці й бере substitute, а не йде в
конкурентну мережу або взагалі відмовляється від покупки?

**Ключова метрика — `COEF_1`** ∈ [0, 1]:
- `COEF_1 ≈ 1.0` → клієнт повністю замінюваний (повністю утримуємо в мережі).
- `COEF_1 ≈ 0.0` → клієнт унікальний (без цього препарату йде з мережі).

**Аналітичний підхід:** Difference-in-Differences (DiD) на рівні
stockout-подій + cross-market агрегація з трьома декомпозиційними метриками
(COVERAGE_PCT, CONDITIONAL_RETENTION, MARKETS_WITH_SUB) і композитним
показником надійності (RELIABILITY_SCORE).

---

## 2. АРХІТЕКТУРА PIPELINE

```
RAW CSV (один файл = один CLIENT_ID = один локальний ринок аптек)
            │
            ▼
        Phase A0 — Discovery
        ├─ Sniff кожного CSV (валідація колонок, CLIENT_ID, розмір)
        └─ Накопичувальний NFC1-registry (data/master/nfc1_config.json)
            │
            ▼
        Phase A1–A4 — Per-Market (паралельно × 6 workers, ProcessPoolExecutor)
        ├─ A1: Aggregation        → aggregated.parquet
        ├─ A2: Stockout Detection → stockout_events.parquet
        ├─ A3: DiD Analysis       → did_events.parquet + substitute_pairs.parquet
        └─ A4: Substitute Shares  → substitute_shares.parquet
            │
            ▼
        Phase B — Cross-Market Aggregation
        └─ За кожним DRUGS_ID: IQR-фільтр → mean SHARE_INTERNAL,
           COVERAGE_PCT, CONDITIONAL_RETENTION, MARKETS_WITH_SUB,
           STD/CV/RELIABILITY_LABEL/RELIABILITY_SCORE,
           Hartigan dip-test (UNIMODAL/MULTIMODAL)
            │
            ▼  data/intermediate/02_cross_market/drug_statistics.parquet
            ▼
        Phase C — Final Export
        ├─ Filter MARKET_COUNT ≥ 20
        ├─ Phantom substitutes filter (SHARE > 0)  ← ISSUE-016
        └─ 16 invariant validation
            │
            ▼  results/final/  (4 файли + validation_report.txt)
```

**Запуск повного pipeline:** `run.bat` (Windows-launcher) — подвійний клік.
Альтернатива: `python -m pipeline.full_run` (з активного venv).

---

## 3. ПОТОЧНИЙ СТАН ПРОЕКТУ

Pipeline пройшов **повний production-cycle** на реальному датасеті
(205 локальних ринків × 152 GB сирих CSV) із результатом:
- 6 264 препарати у фінальному `drug_coefficients.csv` (13 колонок).
- 134 081 пара у фінальному `substitute_shares.csv` (8 колонок).
- 16/16 валідаційних інваріантів PASSED.
- Загальний час обробки: ~6 годин на 6 workers.

Результати **не входять** у репозиторій (виключені через `.gitignore` —
це property замовника). Документація методології (`reports/`,
`docs/`) — публічна, знеособлена.

---

## 4. КЛЮЧОВІ МЕТОДОЛОГІЧНІ РІШЕННЯ (історія розвитку)

Проект пройшов кілька ітерацій методологічних виправлень. Усі задокументовані
в `docs/_methods_issues.md`:

| Issue | Опис | Status |
|-------|------|--------|
| **ISSUE-013** | LOST_SALES математично некоректний у канонічному коді (double-subtract bug) | ✅ FIXED |
| **ISSUE-014** | COEF_1 = median не валідний для MULTIMODAL препаратів | ✅ FIXED — перейшли на mean + 3 декомпозиційні метрики |
| **ISSUE-015** | NFC1 hardcoded список + помилкова ORAL_GROUP (рідкі ↔ тверді) | ✅ FIXED — динамічний master registry, ORAL_SOLID_RETARD only |
| **ISSUE-016** | «Фантомні» substitutes (SHARE = 0) у фінальному файлі | ✅ FIXED — фільтр SHARE > 0 у Phase C, pattern «broad model, narrow export» |

**Версія методології:** v2.1 (станом на 2026-05-01).

---

## 5. КЛЮЧОВІ ФОРМУЛИ

### 5.1 SHARE_INTERNAL (per stockout-event)

```
SHARE_INTERNAL = INTERNAL_LIFT / (INTERNAL_LIFT + LOST_SALES)
```

Реалізація: `core/did.py::calculate_did_for_event`.

### 5.2 COEF_1 (per drug, after cross-market aggregation)

```
COEF_1 = mean(SHARE_INTERNAL after IQR-filter Tukey 1.5×)
       = COVERAGE_PCT × CONDITIONAL_RETENTION    (декомпозиційний інваріант)
```

Реалізація: `pipeline/cross_market.py::aggregate_cross_market`.

### 5.3 RELIABILITY_SCORE (composite)

```
SCORE = stability × sample_factor × modality_penalty   ∈ [0, 1]

де:
  stability        = clip(1 − CV, 0, 1)            (CV = STD/MEAN)
  sample_factor    = min(1, log10(MC_CLEAN) / log10(150))
  modality_penalty = 0.85 if MULTIMODAL else 1.0
```

Реалізація: `pipeline/cross_market.py::calculate_reliability`.

### 5.4 NFC compatibility

Динамічний master registry у `data/master/nfc1_config.json`. Бізнес-правила
(`compatibility_groups`, `excluded`) редагуються вручну, категорії
накопичуються між запусками автоматично з discovery.

Реалізація: `core/nfc.py::is_compatible`.

---

## 6. СТРУКТУРА РЕПОЗИТОРІЮ

```
drug_substitution_engine/
├── README.md / README_UA.md       ← лице репо (англ. + укр.)
├── LICENSE / SECURITY.md          ← proprietary + data privacy
├── CLAUDE_BRIEFING.md             ← цей файл
├── run.bat                        ← Windows-launcher (повний pipeline)
├── requirements.txt               ← pandas 2.3, pyarrow, scipy, diptest, rich
│
├── config/                        ← all parameters (paths, columns, machine, NFC, stockout)
├── core/                          ← бізнес-логіка (etl, did, nfc, stockout, io_utils)
├── pipeline/                      ← orchestration (Phases A0–C, runner, full_run)
│
├── data/
│   ├── master/                    ← accumulating registries (nfc1_config.json — gitignored)
│   └── intermediate/              ← per-market parquet cache (gitignored)
│
├── docs/                          ← методологія (ROADMAP, ALGORITHMS, LOGS, _methods_issues)
├── reports/                       ← звіти (validation, business, data_dictionary)
├── results/final/                 ← Power BI exports (gitignored, .gitkeep тільки)
├── logs/                          ← runtime logs (gitignored)
│
└── _optional_calculations/        ← ad-hoc розрахунки (за запитом)
    ├── README.md                  ← namespace-документ
    ├── top_1k_reliability_sales_volume/   ← перший ad-hoc task
    └── visualizations/                     ← візуалізації для README
```

---

## 7. АРХІТЕКТУРНІ ПРИНЦИПИ (для AI: НЕ ЛАМАЙ ЦЕ)

### 7.1 Separation of pipeline vs ad-hoc

Продакшн-пайплайн (`pipeline/`, `core/`, `config/`) реалізує математично
обґрунтовані розрахунки і **не модифікується під специфічні запити
замовника**. Усі ad-hoc обчислення — у `_optional_calculations/<task_name>/`.

### 7.2 Broad model, narrow export

Intermediate parquet (Phase A3/A4) зберігає повну видимість для
debugging/audit. Фільтри (наприклад, SHARE > 0 у ISSUE-016) застосовуються
**тільки на фінальний експорт** у Phase C.

### 7.3 Math first, business consequences second

Якщо математично коректна формула дає неочікуваний бізнес-результат — формулу
**не ламаємо**. Розв'язання — на рівні ad-hoc скрипту або композиції метрик
(приклад: RELIABILITY_SCORE для COEF_1=0 препаратів формально 1.0, але
ad-hoc-фільтр у `top_1k_reliability_sales_volume` поєднує його з обсягом
продажів через Pareto coverage).

### 7.4 Конфігурованість

Усі параметри (пороги, шляхи, machine specs) — у `config/`. Не hardcode у
business logic. Винятки задокументовані як tech-debt у LOGS.

---

## 8. ЯК ВЛАШТОВАНА ДОКУМЕНТАЦІЯ

При роботі з проектом використовуй ці документи у такому порядку:

| Файл | Коли читати |
|------|-------------|
| `README.md` | швидке знайомство (загальна картина) |
| `CLAUDE_BRIEFING.md` (цей) | контекст для AI-асистента |
| `docs/ROADMAP.md` | план + ухвалені архітектурні рішення |
| `docs/ALGORITHMS.md` | детальна методологія + формули + параметри |
| `docs/LOGS.md` | хронологія робіт (chronological journal) |
| `docs/_methods_issues.md` | каталог методологічних проблем + статусів FIXED |
| `reports/data_dictionary.txt` | опис кожної колонки фінальних файлів |
| `reports/business_report.txt` | бізнес-інтерпретація результатів |
| `reports/validation_report.txt` | звіт валідації (16 інваріантів) |

---

## 9. ЧАСТІ ЗАВДАННЯ — типові сценарії доробок

### 9.1 Зміна порогу методології

**Приклад:** змінити `MIN_MARKET_COUNT` (поточно 20) для зменшення фільтру.

**Як:** CLI-параметр `--min-market-count` у `run.bat` / `python -m pipeline.full_run`.
Документація: `docs/ALGORITHMS.md` (Phase C).

### 9.2 Додати нову бізнес-категорію NFC1 compatibility

**Як:** редагувати `data/master/nfc1_config.json` — секція
`compatibility_groups` (вручну). При наступному запуску discovery
зберігається автоматично.

### 9.3 Ad-hoc запит замовника (фільтр top-N тощо)

**Як:** **НЕ модифікувати** `pipeline/`. Створити нову папку у
`_optional_calculations/<descriptive_name>/` за зразком
`top_1k_reliability_sales_volume/`.

### 9.4 Модифікація методологічної формули

**Як:** обов'язково обговорити з користувачем (це data-science проект, не
software engineering). Зміни мають бути математично обґрунтовані. Завжди
оновлювати:
- `docs/ALGORITHMS.md` (CHANGELOG + опис формули)
- `docs/LOGS.md` (новий запис step-by-step)
- `docs/_methods_issues.md` (якщо це fix існуючої проблеми → ISSUE)
- `reports/data_dictionary.txt` (якщо змінилася колонка)

---

## 10. КРИТИЧНІ ОПЕРАЦІЙНІ НЮАНСИ

### 10.1 Resume-логіка

Pipeline стійкий до перерв. Кожна фаза перевіряє наявність валідного
parquet через `core/io_utils.py::phase_output_valid` (corruption-aware
через `pq.read_metadata`). При повторному запуску виконуються тільки
відсутні фази.

**Важливо:** при зміні методології, що впливає на конкретну фазу, треба
**вручну видалити відповідні parquet** з `data/intermediate/01_per_market/`.

### 10.2 Час виконання

| Сценарій | Час (на 6 workers) |
|----------|---------------------|
| Повний прогон з нуля (152 GB raw) | ~6 годин |
| Resume з кешу A1–A2, перерахунок A3–A4 | ~5 годин |
| Тільки Phase B+C з кешу | ~50 секунд |

### 10.3 ProcessPoolExecutor

Worker count = `MAX_WORKERS` у `config/machine_params.py` (default 6 для
i7-9700 / 8 cores / 32 GB RAM). Кожен worker читає 1 файл (~800 MB max) у
RAM, тож при `--workers 6` пікова RAM ≈ 6 × 2 GB + base.

### 10.4 ProcessPool sympathy

`pipeline/runner.py` має кастомний Rich Live TUI. **Не запускати через
Jupyter** — TUI не сумісний з notebook-stdout. Тільки через
терминал або `run.bat`.

---

## 11. ШВИДКИЙ START на новому ПК

```bash
# 1. Клонувати репо
git clone <repo_url>
cd drug_substitution_engine

# 2. Створити venv (Windows)
python -m venv ../_lib_env

# 3. Встановити dependencies
../_lib_env/Scripts/pip install -r requirements.txt

# 4. Покласти raw CSV у DATA_SETS (шлях у config/paths.py)
# Очікуваний формат: один CSV = один CLIENT_ID, з обов'язковими колонками
# CLIENT_ID, DRUGS_ID, INN, INN_ID, NFC Code (1), Q, V, PERIOD_ID etc.
# (повний список — config/column_mapping.py)

# 5. Запустити повний pipeline
run.bat
# або: ../_lib_env/Scripts/python -m pipeline.full_run

# 6. Результати — у results/final/ + reports/
```

---

## 12. КОНТАКТИ

**Автор:** Radyslav Lomanov
**Email:** lomanov.mail@gmail.com
**Telegram:** [@radyslav_datascience](https://t.me/radyslav_datascience)
**WhatsApp:** [+38 (095) 035-94-05](https://wa.me/380950359405)

При роботі з проектом — питання у вищезазначені канали.

---

**© 2026 Radyslav Lomanov. Proprietary. See [LICENSE](LICENSE).**
