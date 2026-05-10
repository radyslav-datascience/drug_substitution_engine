# =============================================================================
# CONFIG — top_1k_reliability_sales_volume
# =============================================================================
# Призначення: параметри відбору top-N препаратів за обсягом продажів та
# RELIABILITY_SCORE. Редагуй цей файл, щоб змінити поведінку run_filter.py
# без модифікації самого скрипта.
# =============================================================================

from pathlib import Path

# =============================================================================
# ШЛЯХИ
# =============================================================================

TASK_DIR = Path(__file__).resolve().parent

# Вхідний файл від замовника (PowerBI-формат, 16 колонок)
INPUT_POWER_BI_XLSX = TASK_DIR / "inputs" / "drug_coefficients_power_bi_sales_volume.xlsx"

# Джерело RELIABILITY_SCORE — наш фінальний файл v2.1
PROJECT_ROOT = TASK_DIR.parent.parent  # drug_substitution_engine/
DRUG_COEF_CSV = PROJECT_ROOT / "results" / "final" / "drug_coefficients.csv"

# Папки виходу
OUTPUTS_DIR = TASK_DIR / "outputs"
LOGS_DIR    = TASK_DIR / "logs"

# Файли виходу
# Основний — 16 колонок точно як вхідний файл, для Power BI аналітика.
OUTPUT_ANALYSIS_XLSX = OUTPUTS_DIR / "drug_coefficients_power_bi_sales_volume_filtered.xlsx"
OUTPUT_STATISTICS_TXT = OUTPUTS_DIR / "statistics.txt"

# Substitute shares — для run_substitutes_subset.py (другий скрипт у пайплайні).
# Використовуємо наш ПРОДАКШН substitute_shares.csv (results/final), не файл
# від аналітика. Причина: продакшн-файл містить чисті дані без «фантомних»
# substitutes (SHARE=0 виключені у Phase C — ISSUE-016, 2026-05-01).
INPUT_SUBSTITUTE_SHARES = PROJECT_ROOT / "results" / "final" / "substitute_shares.csv"
OUTPUT_SUBSTITUTE_SHARES_XLSX = TASK_DIR / "outputs" / "substitute_shares_power_bi_filtered.xlsx"


# =============================================================================
# ФІЛЬТРАЦІЯ — параметри відбору
# =============================================================================

# Діапазон RELIABILITY_SCORE: препарати поза [MIN, MAX] виключаються.
# 0.0 / 1.0 → без обмеження (бере все).
MIN_RELIABILITY_SCORE: float = 0.70
MAX_RELIABILITY_SCORE: float = 1.0

# Скільки top-N препаратів брати (після сортування за Обсягом DESC).
# None → без обмеження. Ігнорується, якщо задано PARETO_COVERAGE_TARGET.
TOP_N: int = None

# Колонка, за якою сортуємо в кінці (DESC).
SORT_BY_COLUMN: str = "Обсяг (UAH)"

# Pareto coverage: беремо мінімальну кількість препаратів (відсортованих за
# Обсяг DESC), що сумарно покривають PARETO_COVERAGE_TARGET частку загального
# обсягу продажів. Значення в (0, 1]. Класичне правило 80/20: 0.80.
# None → Pareto cut не застосовується; діє TOP_N (якщо задано).
PARETO_COVERAGE_TARGET: float = 0.80

# Чи додавати колонку RELIABILITY_SCORE у вихідний файл.
# True — для внутрішнього аналізу (17 колонок).
# False — для Power BI аналітика: 16 колонок ТОЧНО як вхідний файл.
INCLUDE_RELIABILITY_IN_OUTPUT: bool = False
