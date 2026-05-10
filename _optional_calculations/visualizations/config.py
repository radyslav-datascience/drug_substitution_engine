# =============================================================================
# CONFIG — visualizations
# =============================================================================
# Призначення: параметри генерації графіків для портфоліо/README.
# Редагуй цей файл, щоб змінити пороги, палітру або DPI без модифікації
# самого скрипта run_visualizations.py.
# =============================================================================

from pathlib import Path

# =============================================================================
# ШЛЯХИ
# =============================================================================

TASK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = TASK_DIR.parent.parent  # drug_substitution_engine/

# Джерело: продакшн-вихід v2.1 (всі 6 264 препарати)
DRUG_COEF_CSV = PROJECT_ROOT / "results" / "final" / "drug_coefficients.csv"

# Опціональне джерело sales volume для Pareto-curve.
# Якщо файла немає — Pareto chart буде пропущено (warning у логах).
SALES_VOLUME_XLSX = (
    PROJECT_ROOT
    / "_optional_calculations"
    / "top_1k_reliability_sales_volume"
    / "inputs"
    / "drug_coefficients_power_bi_sales_volume.xlsx"
)
SALES_VOLUME_COLUMN = "Обсяг (UAH)"

# Папки виходу
OUTPUTS_DIR = TASK_DIR / "outputs"
LOGS_DIR    = TASK_DIR / "logs"

# Файли виходу (PNG → ці імена використовуються у README.md)
OUT_DISTRIBUTION_COEF1   = OUTPUTS_DIR / "01_distribution_coef1.png"
OUT_PARETO_VOLUME        = OUTPUTS_DIR / "02_pareto_sales_volume.png"
OUT_SCATTER_DECOMPOSE    = OUTPUTS_DIR / "03_scatter_coverage_conditional.png"
OUT_DISTRIBUTION_RELIAB  = OUTPUTS_DIR / "04_distribution_reliability.png"


# =============================================================================
# ВІЗУАЛЬНІ ПАРАМЕТРИ
# =============================================================================

# Розмір та якість PNG
FIG_SIZE   = (10, 6)   # дюйми; широкий формат для README
FIG_DPI    = 140       # достатньо для retina, без перенавантаження git
SAVE_DPI   = 150

# Палітра
COLOR_PRIMARY      = "#2E86AB"   # синій — основні бари/лінії
COLOR_SECONDARY    = "#A23B72"   # пурпуровий — акценти, MULTIMODAL
COLOR_TERTIARY     = "#F18F01"   # помаранчевий — Pareto cut-off line
COLOR_GRID         = "#E5E5E5"
COLOR_TEXT_MUTED   = "#666666"

# Стиль
USE_GRID    = True
GRID_ALPHA  = 0.4
FONT_FAMILY = "DejaVu Sans"   # підтримує кирилицю


# =============================================================================
# СЕГМЕНТАЦІЯ COEF_1 (тіри A/B/C)
# =============================================================================
# Бізнес-сегментація: препарати з високим COEF_1 утримують лояльність ринку
# при відсутності; з низьким — губляться повністю. Пороги — стандартні
# у фарма-роздробі для tier-based stocking.

TIER_A_THRESHOLD = 0.85   # COEF_1 ≥ 0.85  → «sticky drugs» (А — Critical)
TIER_B_THRESHOLD = 0.55   # 0.55..0.85     → «substitutable» (B — Standard)
                          # COEF_1 < 0.55  → «vulnerable» (C — Watch)


# =============================================================================
# PARETO COVERAGE
# =============================================================================

PARETO_TARGET = 0.80   # 80 % від обсягу — класичне правило 80/20


# =============================================================================
# RELIABILITY HISTOGRAM
# =============================================================================

RELIABILITY_BINS = 30
RELIABILITY_GOOD_THRESHOLD = 0.70   # пороги, які використовує top_1k task


# =============================================================================
# COEF_1 HISTOGRAM
# =============================================================================

COEF1_BINS = 50
