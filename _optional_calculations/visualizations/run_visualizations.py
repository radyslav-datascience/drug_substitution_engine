# =============================================================================
# visualizations — RUN
# =============================================================================
# Призначення: згенерувати 4 PNG-графіки на основі results/final/drug_coefficients.csv
# для портфоліо/README. Параметри читаються з config.py.
# Запуск:
#     python _optional_calculations/visualizations/run_visualizations.py
# =============================================================================

import logging
import sys
from datetime import datetime
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter, PercentFormatter

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import config  # noqa: E402


# =============================================================================
# LOGGING
# =============================================================================

def setup_logging() -> Path:
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = config.LOGS_DIR / f"run_{timestamp}.log"
    # На Windows-консолі (cp1251) Unicode-символи у повідомленнях ламають
    # потоковий лог. Перевідкриваємо stdout як utf-8 з заміною непідтриманих
    # знаків — файловий лог завжди utf-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


# =============================================================================
# СТИЛЬ
# =============================================================================

def apply_style() -> None:
    plt.rcParams.update({
        "font.family": config.FONT_FAMILY,
        "font.size": 11,
        "axes.titlesize": 13,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.edgecolor": config.COLOR_TEXT_MUTED,
        "axes.linewidth": 0.8,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.color": config.COLOR_TEXT_MUTED,
        "ytick.color": config.COLOR_TEXT_MUTED,
        "grid.color": config.COLOR_GRID,
        "grid.alpha": config.GRID_ALPHA,
        "figure.dpi": config.FIG_DPI,
        "savefig.dpi": config.SAVE_DPI,
        "savefig.bbox": "tight",
        "savefig.facecolor": "white",
    })


# =============================================================================
# ДАНІ
# =============================================================================

def load_drug_coefficients() -> pd.DataFrame:
    if not config.DRUG_COEF_CSV.exists():
        raise FileNotFoundError(f"Не знайдено: {config.DRUG_COEF_CSV}")
    df = pd.read_csv(config.DRUG_COEF_CSV, sep=";")
    logging.info(f"  drug_coefficients:  {len(df):>6,} rows x {len(df.columns)} cols")
    return df


def load_sales_volume() -> pd.DataFrame | None:
    if not config.SALES_VOLUME_XLSX.exists():
        logging.warning(
            f"  sales_volume xlsx не знайдено ({config.SALES_VOLUME_XLSX}); "
            "Pareto chart буде пропущено."
        )
        return None
    df = pd.read_excel(config.SALES_VOLUME_XLSX)
    logging.info(f"  sales_volume xlsx:  {len(df):>6,} rows x {len(df.columns)} cols")
    return df


# =============================================================================
# CHART 1 — DISTRIBUTION COEF_1 з тірами A/B/C
# =============================================================================

def chart_distribution_coef1(df: pd.DataFrame) -> None:
    coef1 = df["COEF_1"].dropna().values
    n_a = int((coef1 >= config.TIER_A_THRESHOLD).sum())
    n_b = int(((coef1 >= config.TIER_B_THRESHOLD) & (coef1 < config.TIER_A_THRESHOLD)).sum())
    n_c = int((coef1 < config.TIER_B_THRESHOLD).sum())
    n_total = n_a + n_b + n_c

    fig, ax = plt.subplots(figsize=config.FIG_SIZE)
    counts, bins, patches = ax.hist(
        coef1,
        bins=config.COEF1_BINS,
        edgecolor="white",
        linewidth=0.5,
    )
    # Розмалювати бари за тірами
    for patch, edge in zip(patches, bins[:-1]):
        if edge >= config.TIER_A_THRESHOLD:
            patch.set_facecolor("#3FA34D")     # зелений — Tier A
        elif edge >= config.TIER_B_THRESHOLD:
            patch.set_facecolor(config.COLOR_PRIMARY)
        else:
            patch.set_facecolor(config.COLOR_SECONDARY)

    # Вертикальні роздільники
    for x in (config.TIER_B_THRESHOLD, config.TIER_A_THRESHOLD):
        ax.axvline(x, color=config.COLOR_TEXT_MUTED, linestyle="--", linewidth=1)

    ax.set_title("Розподіл COEF_1 за тірами A/B/C")
    ax.set_xlabel("COEF_1 (mean SHARE_INTERNAL після IQR-trim)")
    ax.set_ylabel("Кількість препаратів")
    ax.grid(True, axis="y")
    ax.set_xlim(0, 1)

    legend_text = (
        f"Tier A  (≥ {config.TIER_A_THRESHOLD:.2f}):  {n_a:>5,}  ({n_a/n_total:.1%})\n"
        f"Tier B  ({config.TIER_B_THRESHOLD:.2f}–{config.TIER_A_THRESHOLD:.2f}):  {n_b:>5,}  ({n_b/n_total:.1%})\n"
        f"Tier C  (< {config.TIER_B_THRESHOLD:.2f}):  {n_c:>5,}  ({n_c/n_total:.1%})\n"
        f"Total:                  {n_total:>5,}"
    )
    ax.text(
        0.02, 0.98, legend_text,
        transform=ax.transAxes,
        fontsize=10,
        family="monospace",
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.6", facecolor="white",
                  edgecolor=config.COLOR_GRID, alpha=0.95),
    )

    fig.tight_layout()
    fig.savefig(config.OUT_DISTRIBUTION_COEF1)
    plt.close(fig)
    logging.info(f"  ✓ {config.OUT_DISTRIBUTION_COEF1.name}  (A={n_a}, B={n_b}, C={n_c})")


# =============================================================================
# CHART 2 — PARETO CURVE (sales volume)
# =============================================================================

def chart_pareto_volume(df_sales: pd.DataFrame) -> None:
    col = config.SALES_VOLUME_COLUMN
    if col not in df_sales.columns:
        logging.warning(f"  sales_volume xlsx не містить колонки '{col}'; chart пропущено.")
        return

    volumes = df_sales[col].dropna().sort_values(ascending=False).values
    total = volumes.sum()
    cum_share = np.cumsum(volumes) / total
    n_drugs = np.arange(1, len(volumes) + 1)

    n_at_target = int(np.searchsorted(cum_share, config.PARETO_TARGET) + 1)
    pct_at_target = n_at_target / len(volumes)

    fig, ax = plt.subplots(figsize=config.FIG_SIZE)
    ax.plot(n_drugs, cum_share, color=config.COLOR_PRIMARY, linewidth=2)

    ax.axhline(config.PARETO_TARGET, color=config.COLOR_TERTIARY,
               linestyle="--", linewidth=1.2,
               label=f"{config.PARETO_TARGET:.0%} обсягу")
    ax.axvline(n_at_target, color=config.COLOR_TERTIARY,
               linestyle="--", linewidth=1.2)

    ax.scatter([n_at_target], [config.PARETO_TARGET],
               color=config.COLOR_TERTIARY, s=70, zorder=5)
    ax.annotate(
        f"{n_at_target:,} препаратів  ({pct_at_target:.1%})\n"
        f"= {config.PARETO_TARGET:.0%} обороту мережі",
        xy=(n_at_target, config.PARETO_TARGET),
        xytext=(n_at_target * 1.15, config.PARETO_TARGET - 0.18),
        fontsize=10,
        arrowprops=dict(arrowstyle="->", color=config.COLOR_TEXT_MUTED, lw=0.8),
        bbox=dict(boxstyle="round,pad=0.4", facecolor="white",
                  edgecolor=config.COLOR_GRID, alpha=0.95),
    )

    ax.set_title("Pareto-крива: кумулятивна частка обсягу продажів")
    ax.set_xlabel("Кількість препаратів (відсортовано за обсягом DESC)")
    ax.set_ylabel("Кумулятивна частка обороту")
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_xlim(0, len(volumes))
    ax.set_ylim(0, 1.02)
    ax.grid(True)
    ax.legend(loc="lower right", framealpha=0.95)

    fig.tight_layout()
    fig.savefig(config.OUT_PARETO_VOLUME)
    plt.close(fig)
    logging.info(
        f"  ✓ {config.OUT_PARETO_VOLUME.name}  "
        f"({n_at_target:,} препаратів = {config.PARETO_TARGET:.0%} обороту)"
    )


# =============================================================================
# CHART 3 — SCATTER COVERAGE_PCT × CONDITIONAL_RETENTION
# =============================================================================

def chart_scatter_decompose(df: pd.DataFrame) -> None:
    sub = df.dropna(subset=["COVERAGE_PCT", "CONDITIONAL_RETENTION", "DRUG_CLASS"]).copy()

    fig, ax = plt.subplots(figsize=config.FIG_SIZE)

    uni = sub[sub["DRUG_CLASS"] == "UNIMODAL"]
    multi = sub[sub["DRUG_CLASS"] == "MULTIMODAL"]

    ax.scatter(uni["COVERAGE_PCT"], uni["CONDITIONAL_RETENTION"],
               s=8, alpha=0.35, color=config.COLOR_PRIMARY,
               label=f"UNIMODAL (n={len(uni):,})", edgecolors="none")
    ax.scatter(multi["COVERAGE_PCT"], multi["CONDITIONAL_RETENTION"],
               s=10, alpha=0.55, color=config.COLOR_SECONDARY,
               label=f"MULTIMODAL (n={len(multi):,})", edgecolors="none")

    # Контури COEF_1 = COVERAGE × CONDITIONAL = const
    x = np.linspace(0.001, 1.0, 200)
    for c in (0.25, 0.50, 0.75):
        y = np.clip(c / x, 0, 1)
        mask = (y > 0) & (y <= 1)
        ax.plot(x[mask], y[mask], color=config.COLOR_TEXT_MUTED,
                linestyle=":", linewidth=0.8, alpha=0.7)
        # Підпис на лінії
        x_label = c / 0.85
        if 0 < x_label < 1:
            ax.text(x_label, 0.86, f"COEF_1 = {c:.2f}",
                    fontsize=8, color=config.COLOR_TEXT_MUTED,
                    rotation=-25, ha="left", va="bottom")

    ax.set_title("Декомпозиція: COEF_1 = COVERAGE_PCT × CONDITIONAL_RETENTION")
    ax.set_xlabel("COVERAGE_PCT (частка ринків з SHARE > 0)")
    ax.set_ylabel("CONDITIONAL_RETENTION (середня внутрішня частка коли є)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.xaxis.set_major_formatter(PercentFormatter(1.0))
    ax.yaxis.set_major_formatter(PercentFormatter(1.0))
    ax.grid(True)
    ax.legend(loc="lower left", framealpha=0.95)

    fig.tight_layout()
    fig.savefig(config.OUT_SCATTER_DECOMPOSE)
    plt.close(fig)
    logging.info(
        f"  ✓ {config.OUT_SCATTER_DECOMPOSE.name}  "
        f"(UNIMODAL={len(uni):,}, MULTIMODAL={len(multi):,})"
    )


# =============================================================================
# CHART 4 — DISTRIBUTION RELIABILITY_SCORE
# =============================================================================

def chart_distribution_reliability(df: pd.DataFrame) -> None:
    rel = df["RELIABILITY_SCORE"].dropna().values
    n_total = len(rel)
    n_good = int((rel >= config.RELIABILITY_GOOD_THRESHOLD).sum())

    fig, ax = plt.subplots(figsize=config.FIG_SIZE)
    counts, bins, patches = ax.hist(
        rel,
        bins=config.RELIABILITY_BINS,
        edgecolor="white",
        linewidth=0.5,
    )
    for patch, edge in zip(patches, bins[:-1]):
        if edge >= config.RELIABILITY_GOOD_THRESHOLD:
            patch.set_facecolor("#3FA34D")
        else:
            patch.set_facecolor(config.COLOR_PRIMARY)

    ax.axvline(config.RELIABILITY_GOOD_THRESHOLD,
               color=config.COLOR_TERTIARY, linestyle="--", linewidth=1.2,
               label=f"поріг надійності = {config.RELIABILITY_GOOD_THRESHOLD:.2f}")

    median = float(np.median(rel))
    mean   = float(np.mean(rel))

    ax.set_title("Розподіл RELIABILITY_SCORE (composite: stability × sample × modality)")
    ax.set_xlabel("RELIABILITY_SCORE  ∈ [0, 1]")
    ax.set_ylabel("Кількість препаратів")
    ax.grid(True, axis="y")
    ax.set_xlim(0, 1)

    info_text = (
        f"n total:    {n_total:>5,}\n"
        f"median:     {median:>5.3f}\n"
        f"mean:       {mean:>5.3f}\n"
        f"≥ {config.RELIABILITY_GOOD_THRESHOLD:.2f}:    {n_good:>5,}  ({n_good/n_total:.1%})"
    )
    ax.text(
        0.02, 0.98, info_text,
        transform=ax.transAxes,
        fontsize=10,
        family="monospace",
        verticalalignment="top",
        bbox=dict(boxstyle="round,pad=0.6", facecolor="white",
                  edgecolor=config.COLOR_GRID, alpha=0.95),
    )
    ax.legend(loc="upper right", framealpha=0.95)

    fig.tight_layout()
    fig.savefig(config.OUT_DISTRIBUTION_RELIAB)
    plt.close(fig)
    logging.info(
        f"  ✓ {config.OUT_DISTRIBUTION_RELIAB.name}  "
        f"(median={median:.3f}, ≥{config.RELIABILITY_GOOD_THRESHOLD}: {n_good:,})"
    )


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    log_path = setup_logging()
    apply_style()
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    logging.info("=" * 70)
    logging.info("VISUALIZATIONS — генерація 4 PNG для README/портфоліо")
    logging.info("=" * 70)

    df = load_drug_coefficients()
    df_sales = load_sales_volume()

    chart_distribution_coef1(df)
    if df_sales is not None:
        chart_pareto_volume(df_sales)
    chart_scatter_decompose(df)
    chart_distribution_reliability(df)

    logging.info("-" * 70)
    logging.info(f"Готово. PNG → {config.OUTPUTS_DIR}")
    logging.info(f"Log → {log_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
