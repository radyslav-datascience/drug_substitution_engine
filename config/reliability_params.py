# =============================================================================
# RELIABILITY PARAMETERS - drug_substitution_engine
# =============================================================================
# Файл: config/reliability_params.py
# Дата: 2026-05-11
# Опис: Параметри RELIABILITY_LABEL та RELIABILITY_SCORE (Phase B).
# =============================================================================

"""
Параметри композитного RELIABILITY_SCORE та canonical-style RELIABILITY_LABEL.

Виокремлено з `pipeline/cross_market.py` (ISSUE-013/015 follow-up) у
config-файл, щоб:
    - параметри методології лежали в одному місці з іншими (stockout_params,
      column_mapping тощо);
    - ad-hoc-задачі в `_optional_calculations/` могли імпортувати ті ж самі
      значення без дублювання (наприклад, `top_1k_reliability_sales_volume`
      посилається на той самий поріг через RELIABILITY_SCORE-фільтр);
    - зміна порогу не вимагала редагування продакшн-пайплайну.

Документація методології: `docs/ALGORITHMS.md`,
`docs/_methods_issues.md::ISSUE-015`.

Використання:
    from config.reliability_params import (
        RELIABILITY_HIGH_THRESHOLD,
        RELIABILITY_MEDIUM_THRESHOLD,
        SAMPLE_SATURATION_MARKETS,
        MULTIMODAL_PENALTY,
    )
"""


# =============================================================================
# RELIABILITY_LABEL — canonical-style категорійна оцінка
# =============================================================================
# Базується на коефіцієнті варіації CV = std / mean (SHARE_INTERNAL по ринках).
# CV < RELIABILITY_HIGH_THRESHOLD                   → HIGH
# RELIABILITY_HIGH ≤ CV < RELIABILITY_MEDIUM        → MEDIUM
# CV ≥ RELIABILITY_MEDIUM                           → LOW
# n_markets == 1                                    → SINGLE_MARKET (окремий клас)

# CV < 0.15 — препарат поводиться однаково на всіх ринках, оцінка надійна.
RELIABILITY_HIGH_THRESHOLD:   float = 0.15

# CV < 0.30 — помірний розкид; оцінка робоча, але з застереженням.
RELIABILITY_MEDIUM_THRESHOLD: float = 0.30


# =============================================================================
# RELIABILITY_SCORE — композитний 0..1
# =============================================================================
# Формула:
#     stability        = clip(1 - CV, 0, 1)
#     sample_factor    = min(1, log10(n_markets) / log10(SAMPLE_SATURATION_MARKETS))
#     modality_penalty = MULTIMODAL_PENALTY якщо MULTIMODAL інакше 1.0
#     SCORE            = stability × sample_factor × modality_penalty

# Скільки ринків достатньо, щоб довіряти оцінці (sample_factor → 1.0).
# Обрано 150 за реальним розподілом у датасеті: вище — оцінка стабілізується.
SAMPLE_SATURATION_MARKETS: int = 150

# Штраф для MULTIMODAL-препаратів: середнє SHARE_INTERNAL менш репрезентативне,
# коли розподіл по ринках має 2+ моди (Hartigan dip test p < 0.05).
# 0.85 = «зменшити SCORE на 15 %, але не до нуля» (не дискваліфікувати
# препарат, лише знизити пріоритет у sort-by-reliability).
MULTIMODAL_PENALTY: float = 0.85
