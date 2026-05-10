# =============================================================================
# top_1k_reliability_sales_volume — RUN FILTER
# =============================================================================
# Призначення: відбір препаратів за подвійним фільтром (sales volume x reliability).
# Параметри читаються з config.py — не редагуй цей скрипт для зміни порогів.
# Запуск:
#     python _optional_calculations/top_1k_reliability_sales_volume/run_filter.py
# =============================================================================

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# Локальний config (поряд із цим скриптом)
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import config  # noqa: E402


# =============================================================================
# LOGGING
# =============================================================================

def setup_logging() -> Path:
    """Persistent file-log + console."""
    config.LOGS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = config.LOGS_DIR / f"run_{timestamp}.log"

    fmt = "%(asctime)s [%(levelname)s] %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.FileHandler(log_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return log_path


# =============================================================================
# DATA LOADING & MERGE
# =============================================================================

def load_inputs() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Завантажити вхідний PowerBI xlsx та drug_coefficients.csv (v2.1)."""
    if not config.INPUT_POWER_BI_XLSX.exists():
        raise FileNotFoundError(f"Не знайдено вхідний файл: {config.INPUT_POWER_BI_XLSX}")
    if not config.DRUG_COEF_CSV.exists():
        raise FileNotFoundError(f"Не знайдено drug_coefficients.csv: {config.DRUG_COEF_CSV}")

    df_input = pd.read_excel(config.INPUT_POWER_BI_XLSX)
    df_v2    = pd.read_csv(config.DRUG_COEF_CSV, sep=";")

    logging.info(f"  input PowerBI:   {len(df_input):>6,} rows x {len(df_input.columns)} cols")
    logging.info(f"  drug_coef v2.1:  {len(df_v2):>6,} rows x {len(df_v2.columns)} cols")
    return df_input, df_v2


def merge_reliability(df_input: pd.DataFrame, df_v2: pd.DataFrame) -> tuple[pd.DataFrame, int, int]:
    """
    LEFT JOIN: до df_input додати RELIABILITY_SCORE з df_v2 по DRUGS_ID.

    Returns:
        (merged_df, n_matched, n_unmatched)
    """
    rel = df_v2[["DRUGS_ID", "RELIABILITY_SCORE"]].copy()
    merged = df_input.merge(rel, on="DRUGS_ID", how="left")

    n_unmatched = int(merged["RELIABILITY_SCORE"].isna().sum())
    n_matched   = len(merged) - n_unmatched
    return merged, n_matched, n_unmatched


# =============================================================================
# FILTER & SORT
# =============================================================================

def apply_filter_and_sort(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """
    Застосувати поріг RELIABILITY_SCORE, виключити NaN, відсортувати,
    застосувати Pareto/TOP_N обрізання.

    Returns:
        (filtered_df, info) — info містить метрики для звіту:
            n_after_score, n_after_pareto, pareto_coverage_actual, etc.
    """
    info = {}
    n0 = len(df)
    df = df.dropna(subset=["RELIABILITY_SCORE"]).copy()
    n_after_dropna = len(df)
    logging.info(f"  після dropna RELIABILITY_SCORE NaN:  {n_after_dropna:,} (-{n0 - n_after_dropna})")

    df = df[(df["RELIABILITY_SCORE"] >= config.MIN_RELIABILITY_SCORE) &
            (df["RELIABILITY_SCORE"] <= config.MAX_RELIABILITY_SCORE)].copy()
    n_after_score = len(df)
    logging.info(f"  після score range [{config.MIN_RELIABILITY_SCORE}, {config.MAX_RELIABILITY_SCORE}]: "
                 f"{n_after_score:,} (-{n_after_dropna - n_after_score})")
    info["n_after_score"] = n_after_score

    df = df.sort_values(config.SORT_BY_COLUMN, ascending=False).reset_index(drop=True)

    # Pareto coverage cut (пріоритет над TOP_N якщо обидва задано)
    if config.PARETO_COVERAGE_TARGET is not None and len(df) > 0:
        target = float(config.PARETO_COVERAGE_TARGET)
        if not (0 < target <= 1):
            raise ValueError(f"PARETO_COVERAGE_TARGET має бути в (0, 1], отримано {target}")

        total = df[config.SORT_BY_COLUMN].sum()
        cum_pct = df[config.SORT_BY_COLUMN].cumsum() / total
        # Беремо мінімум препаратів, чий cumsum>=target (тобто перший, що перетинає поріг включно)
        n_take = int((cum_pct < target).sum()) + 1
        n_take = min(n_take, len(df))

        actual_coverage = float(cum_pct.iloc[n_take - 1])
        df = df.head(n_take).copy()
        logging.info(f"  після Pareto cut (target={target:.0%}):  {len(df):,}  "
                     f"(actual coverage = {actual_coverage:.2%}, sum = {df[config.SORT_BY_COLUMN].sum():,.0f} UAH "
                     f"з {total:,.0f})")
        info["pareto_target"] = target
        info["pareto_n"] = n_take
        info["pareto_actual_coverage"] = actual_coverage
        info["total_volume"] = float(total)
    elif config.TOP_N is not None and len(df) > config.TOP_N:
        df = df.head(config.TOP_N).copy()
        logging.info(f"  після top-{config.TOP_N}:  {len(df):,}")
        info["top_n"] = config.TOP_N

    return df, info


# =============================================================================
# OUTPUTS
# =============================================================================

def write_analysis_xlsx(df: pd.DataFrame, df_input: pd.DataFrame) -> None:
    """
    Записати xlsx з тими ж колонками, тим же sheet name та тими ж dtypes,
    що у вхідному файлі — для drop-in заміни в Power BI.
    """
    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    df_out = df.copy()
    if not config.INCLUDE_RELIABILITY_IN_OUTPUT and "RELIABILITY_SCORE" in df_out.columns:
        df_out = df_out.drop(columns=["RELIABILITY_SCORE"])

    # Зберігаємо dtypes точно як у вхідному файлі (захист від pandas автоконверсії,
    # наприклад COVERAGE_PCT all=1.0 → int64; має лишитися float64).
    for col in df_out.columns:
        if col in df_input.columns and df_input[col].dtype != df_out[col].dtype:
            try:
                df_out[col] = df_out[col].astype(df_input[col].dtype)
            except Exception as e:
                logging.warning(f"  could not cast {col} to {df_input[col].dtype}: {e}")

    # Sheet name точно як у вхідному файлі + number_format для float-колонок
    # (захист від pandas re-inference як int при round-trip xlsx → read).
    float_cols = [c for c in df_out.columns if str(df_input[c].dtype).startswith("float")]
    with pd.ExcelWriter(config.OUTPUT_ANALYSIS_XLSX, engine="openpyxl") as writer:
        df_out.to_excel(writer, index=False, sheet_name="Drug Coefficients")
        ws = writer.sheets["Drug Coefficients"]
        col_letters = {c: chr(ord("A") + i) for i, c in enumerate(df_out.columns)}
        for c in float_cols:
            letter = col_letters[c]
            for cell in ws[letter][1:]:  # skip header row
                cell.number_format = "0.000000"
    logging.info(f"  xlsx written: {config.OUTPUT_ANALYSIS_XLSX.name} "
                 f"({df_out.shape[0]:,} rows x {df_out.shape[1]} cols, "
                 f"{config.OUTPUT_ANALYSIS_XLSX.stat().st_size / 1024:.1f} KB)")


def write_statistics_txt(
    df_input: pd.DataFrame,
    df_merged: pd.DataFrame,
    n_matched: int,
    n_unmatched: int,
    df_filtered: pd.DataFrame,
    filter_info: dict,
) -> None:
    """Записати statistics.txt — повний звіт для аналізу."""
    lines = []
    L = lines.append
    sep = "=" * 78

    L(sep)
    L(" STATISTICS — top_1k_reliability_sales_volume")
    L(sep)
    L(f" Сформовано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    L("")
    L(" === 1. Обсяги вхідних/вихідних даних ===")
    L(f"   Вхідний PowerBI файл:                  {len(df_input):>6,} препаратів")
    L(f"   Знайдено в drug_coefficients v2.1:     {n_matched:>6,}  (з RELIABILITY_SCORE)")
    L(f"   НЕ знайдено (orphans, виключені):      {n_unmatched:>6,}")
    L(f"   Поточний фільтр RELIABILITY_SCORE:     [{config.MIN_RELIABILITY_SCORE}, {config.MAX_RELIABILITY_SCORE}]")
    L(f"   Після RELIABILITY-фільтра:             {filter_info.get('n_after_score', '-'):>6,}")
    if "pareto_target" in filter_info:
        L(f"   Pareto coverage target:                {filter_info['pareto_target']:.0%}")
        L(f"   Pareto actual coverage:                {filter_info['pareto_actual_coverage']:.2%}")
        L(f"   Сумарний обсяг ВСІХ матчинг-препаратів: {filter_info['total_volume']:>20,.0f} UAH")
        L(f"   Сумарний обсяг ОБРАНИХ препаратів:      {df_filtered[config.SORT_BY_COLUMN].sum():>20,.0f} UAH")
    elif "top_n" in filter_info:
        L(f"   Поточний TOP_N:                        {filter_info['top_n']}")
    else:
        L(f"   Pareto/TOP_N cut:                      без обмеження")
    L(f"   Препаратів у вихідному файлі:          {len(df_filtered):>6,}")
    L("")
    L(" === 2. Розподіл RELIABILITY_SCORE серед усіх matched препаратів ===")
    s = df_merged["RELIABILITY_SCORE"].dropna()
    L(f"   count={len(s):,}  min={s.min():.4f}  max={s.max():.4f}")
    L(f"   mean={s.mean():.4f}  median={s.median():.4f}  std={s.std():.4f}")
    for q in [0.10, 0.25, 0.50, 0.75, 0.90]:
        L(f"   percentile {int(q*100):>2}: {s.quantile(q):.4f}")
    L("")
    L(" === 3. Розподіл по бакетах RELIABILITY_SCORE ===")
    bins = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0001]
    labels = [f"[{bins[i]:.1f}, {bins[i+1]:.1f})" for i in range(len(bins)-1)]
    cuts = pd.cut(s, bins=bins, labels=labels, right=False, include_lowest=True)
    counts = cuts.value_counts().sort_index()
    cumul = 0
    L(f"   {'Bucket':<14}  {'Count':>6}  {'Cumul':>6}  {'Pct':>5}")
    for label, n in counts.items():
        cumul += n
        L(f"   {label:<14}  {n:>6,}  {cumul:>6,}  {n/len(s)*100:>4.1f}%")
    L("")
    L(" === 4. Скільки препаратів пройшло б за різних порогів MIN_RELIABILITY_SCORE ===")
    L(f"   (з {n_matched:,} matched препаратів)")
    L(f"   {'Threshold':>10}  {'Pass':>6}  {'Pct':>5}")
    for thr in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9]:
        n_pass = int((s >= thr).sum())
        L(f"   >= {thr:>5.2f}  {n_pass:>6,}  {n_pass/n_matched*100:>4.1f}%")
    L("")
    L(" === 5. Топ-20 препаратів за обсягом продажів (з RELIABILITY_SCORE) ===")
    L(f"   {'#':>3}  {'DRUGS_ID':>8}  {'Обсяг (UAH)':>16}  {'COEF_1':>7}  {'REL_SCORE':>9}  Назва")
    top20 = df_merged.dropna(subset=["RELIABILITY_SCORE"]).sort_values(
        "Обсяг (UAH)", ascending=False).head(20)
    for i, (_, r) in enumerate(top20.iterrows(), 1):
        name = str(r["DRUGS_NAME"])[:50] if not pd.isna(r["DRUGS_NAME"]) else ""
        L(f"   {i:>3}  {int(r['DRUGS_ID']):>8}  {r['Обсяг (UAH)']:>16,.0f}  "
          f"{r['COEF_1']:>7.4f}  {r['RELIABILITY_SCORE']:>9.4f}  {name}")
    L("")
    L(" === 6. Розподіл RELIABILITY_SCORE серед топ-1000 за обсягом ===")
    top1000 = df_merged.dropna(subset=["RELIABILITY_SCORE"]).sort_values(
        "Обсяг (UAH)", ascending=False).head(1000)
    sr = top1000["RELIABILITY_SCORE"]
    L(f"   count={len(sr):,}  mean={sr.mean():.4f}  median={sr.median():.4f}")
    L(f"   percentile 25={sr.quantile(0.25):.4f}  percentile 75={sr.quantile(0.75):.4f}")
    for thr in [0.3, 0.5, 0.7, 0.85]:
        L(f"   серед top-1000 з SCORE >= {thr:.2f}:  {int((sr >= thr).sum()):>4,}")
    L("")
    L(sep)

    config.OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_STATISTICS_TXT.write_text("\n".join(lines), encoding="utf-8")
    logging.info(f"  txt written: {config.OUTPUT_STATISTICS_TXT.name} "
                 f"({config.OUTPUT_STATISTICS_TXT.stat().st_size / 1024:.1f} KB)")


# =============================================================================
# MAIN
# =============================================================================

def main() -> int:
    log_path = setup_logging()
    t0 = time.time()
    logging.info("=" * 70)
    logging.info("RUN top_1k_reliability_sales_volume — start")
    logging.info("=" * 70)
    logging.info(f"config: MIN={config.MIN_RELIABILITY_SCORE}  MAX={config.MAX_RELIABILITY_SCORE}  "
                 f"TOP_N={config.TOP_N}  INCLUDE_REL={config.INCLUDE_RELIABILITY_IN_OUTPUT}")
    logging.info("")

    try:
        logging.info("[1/4] Loading inputs...")
        df_input, df_v2 = load_inputs()

        logging.info("[2/4] Merging RELIABILITY_SCORE...")
        df_merged, n_matched, n_unmatched = merge_reliability(df_input, df_v2)
        logging.info(f"  matched:    {n_matched:,}")
        logging.info(f"  unmatched:  {n_unmatched:,}  (виключаються — відсутні у drug_coefficients v2.1)")

        logging.info("[3/4] Apply filter + sort...")
        df_filtered, filter_info = apply_filter_and_sort(df_merged)

        logging.info("[4/4] Writing outputs...")
        write_analysis_xlsx(df_filtered, df_input)
        write_statistics_txt(df_input, df_merged, n_matched, n_unmatched, df_filtered, filter_info)

        elapsed = time.time() - t0
        logging.info("")
        logging.info(f"DONE in {elapsed:.1f}s — log: {log_path}")
        logging.info("=" * 70)
        return 0
    except Exception as e:
        logging.exception(f"FAILED: {type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
