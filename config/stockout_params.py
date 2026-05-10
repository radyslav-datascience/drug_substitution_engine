# =============================================================================
# STOCKOUT & DiD PARAMETERS - drug_substitution_engine
# =============================================================================
# Файл: config/stockout_params.py
# Дата: 2026-04-27
# Опис: Параметри stock-out detection, DiD analysis, NOTSOLD фільтрації
# =============================================================================

"""
Параметри для Phase A1-A4 (per-market processing).

Скопійовано з canonical/project_core/did_config/stockout_params.py
без змін (методологія валідована канонічним проектом).

Групи параметрів:
    1. NOTSOLD filter (Phase A1)
    2. Stock-out detection (Phase A2)
    3. DiD analysis (Phase A3)
    4. Market growth & shares (Phase A3)

Документація методології: див. ALGORITHMS.md та canonical docs/01_did_processing/
"""


# =============================================================================
# NOTSOLD FILTER (Phase A1)
# =============================================================================

# Препарат повинен мати stock-out події (пропорція тижнів без продажів).
MIN_NOTSOLD_PERCENT: float = 0.20   # Мінімум 20% тижнів без продажів
MAX_NOTSOLD_PERCENT: float = 0.95   # Максимум 95% (інакше препарат майже не продається)


# =============================================================================
# STOCK-OUT DETECTION (Phase A2)
# =============================================================================

# Мінімальна тривалість stock-out події (тижнів)
MIN_STOCKOUT_WEEKS: int = 1

# Мінімальна тривалість PRE-періоду (для baseline)
MIN_PRE_PERIOD_WEEKS: int = 4


# =============================================================================
# DiD ANALYSIS (Phase A3)
# =============================================================================

# POST-період
MIN_POST_PERIOD_WEEKS: int = 4   # Мінімум тижнів POST-періоду
MAX_POST_GAP_WEEKS:    int = 2   # Максимальний gap до відновлення продажів

# Мінімальна частка тижнів з продажами в POST
MIN_SALES_WEEKS_RATIO: float = 0.5


# =============================================================================
# MARKET GROWTH & SHARES (Phase A3)
# =============================================================================

# Мінімальні продажі ринку в PRE-періоді для розрахунку MARKET_GROWTH
MIN_MARKET_PRE: float = 1.0

# Мінімальний TOTAL_EFFECT для розрахунку SHARE
MIN_TOTAL_FOR_SHARE: float = 0.001


# =============================================================================
# VALIDATION
# =============================================================================

def validate_params() -> bool:
    """Sanity check at import time."""
    assert MIN_STOCKOUT_WEEKS >= 1
    assert MIN_PRE_PERIOD_WEEKS >= 1
    assert MIN_POST_PERIOD_WEEKS >= 1
    assert 0 < MIN_NOTSOLD_PERCENT < MAX_NOTSOLD_PERCENT < 1
    assert 0 < MIN_SALES_WEEKS_RATIO <= 1
    return True


validate_params()


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("STOCKOUT & DiD PARAMETERS — drug_substitution_engine")
    print("=" * 60)
    print("\nNOTSOLD filter (Phase A1):")
    print(f"  MIN_NOTSOLD_PERCENT:   {MIN_NOTSOLD_PERCENT:.0%}")
    print(f"  MAX_NOTSOLD_PERCENT:   {MAX_NOTSOLD_PERCENT:.0%}")
    print("\nStock-out detection (Phase A2):")
    print(f"  MIN_STOCKOUT_WEEKS:    {MIN_STOCKOUT_WEEKS}")
    print(f"  MIN_PRE_PERIOD_WEEKS:  {MIN_PRE_PERIOD_WEEKS}")
    print("\nDiD analysis (Phase A3):")
    print(f"  MIN_POST_PERIOD_WEEKS: {MIN_POST_PERIOD_WEEKS}")
    print(f"  MAX_POST_GAP_WEEKS:    {MAX_POST_GAP_WEEKS}")
    print(f"  MIN_SALES_WEEKS_RATIO: {MIN_SALES_WEEKS_RATIO}")
    print("\nMarket growth & shares (Phase A3):")
    print(f"  MIN_MARKET_PRE:        {MIN_MARKET_PRE}")
    print(f"  MIN_TOTAL_FOR_SHARE:   {MIN_TOTAL_FOR_SHARE}")
    print(f"\nValidation: PASSED")
