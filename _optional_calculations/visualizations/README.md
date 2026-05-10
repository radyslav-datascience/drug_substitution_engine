# visualizations

Ad-hoc розрахунок: генерація **4 PNG-графіків** для README та портфоліо
на основі продакшн-виходу `results/final/drug_coefficients.csv`.

Графіки демонструють методологію без розкриття клієнтських даних — імена
препаратів і конкретні DRUGS_ID на графіках не показуються, тільки
агреговані розподіли.


---

## ⚡ Порядок запуску

З кореня проекту `drug_substitution_engine/` — будь-який Python-інтерпретатор
з `requirements.txt` (включно з `matplotlib`) спрацює:

```bash
# Локальний venv (рекомендовано):
.venv\Scripts\python.exe _optional_calculations/visualizations/run_visualizations.py

# Або (Linux/macOS):
.venv/bin/python _optional_calculations/visualizations/run_visualizations.py

# Або system Python:
python _optional_calculations/visualizations/run_visualizations.py
```

PNG-файли з'являться в `outputs/`. README.md проекту посилається саме на
ці шляхи — тому імена змінювати не варто (інакше markdown-посилання
у README зламаються).


---

## 📊 Що згенерує скрипт

| № | Файл | Що показує |
|---|------|------------|
| 1 | `01_distribution_coef1.png`           | Розподіл COEF_1 з тірами A/B/C (стратегія наявності) |
| 2 | `02_pareto_sales_volume.png`          | Pareto 80/20 — обґрунтування cutoff обсягу продажів |
| 3 | `03_scatter_coverage_conditional.png` | Декомпозиція COEF_1 = COVERAGE × CONDITIONAL з контурами рівня |
| 4 | `04_distribution_reliability.png`     | Розподіл RELIABILITY_SCORE з порогом 0.70 |

> Графік 2 (Pareto) потребує `sales_volume xlsx` — якщо файла немає, він
> буде пропущений (warning у логах) і три інші графіки згенеруються без помилки.


---

## Параметри (config.py)

| Параметр | Значення default | Опис |
|----------|------------------|------|
| `TIER_A_THRESHOLD`           | 0.85 | Поріг A-tier (sticky drugs) |
| `TIER_B_THRESHOLD`           | 0.55 | Поріг B-tier (substitutable) |
| `PARETO_TARGET`              | 0.80 | Цільове % покриття обороту |
| `RELIABILITY_GOOD_THRESHOLD` | 0.70 | Поріг «надійних» препаратів |
| `COEF1_BINS`                 | 50   | Кількість bins у гістограмі COEF_1 |
| `RELIABILITY_BINS`           | 30   | Кількість bins у гістограмі RELIABILITY |
| `FIG_SIZE`                   | (10, 6) | Розмір фігури в дюймах |
| `SAVE_DPI`                   | 150  | DPI збереженого PNG |


---

## Структура папки

```
visualizations/
├── README.md                  ← цей файл
├── config.py                  ← параметри відображення
├── run_visualizations.py      ← єдиний скрипт-генератор
├── outputs/
│   ├── 01_distribution_coef1.png
│   ├── 02_pareto_sales_volume.png
│   ├── 03_scatter_coverage_conditional.png
│   └── 04_distribution_reliability.png
└── logs/
    └── run_YYYYMMDD_HHMMSS.log
```


---

## Залежності

### Read-only
- `results/final/drug_coefficients.csv` — продакшн-вихід v2.1.
- `_optional_calculations/top_1k_reliability_sales_volume/inputs/drug_coefficients_power_bi_sales_volume.xlsx`
   — джерело sales volume для Pareto-curve (опціонально).

### Не зачіпає
- `pipeline/`, `core/`, `config/` — продакшн-пайплайн НЕ модифікується.
- `results/final/` — оригінали НЕ змінюються.

### Python-пакети
- `pandas`, `numpy`, `matplotlib`, `openpyxl` (для `.xlsx`).
  Встановлюються через `requirements.txt` основного проекту.


---

## Версія

- **v1** (2026-04-27) — 4 базові графіки для public README.
