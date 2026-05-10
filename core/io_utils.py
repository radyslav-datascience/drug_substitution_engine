# =============================================================================
# I/O UTILS - drug_substitution_engine
# =============================================================================
# Файл: core/io_utils.py
# Дата: 2026-04-27
# Опис: Утиліти для безпечного I/O з robust resume logic.
# =============================================================================

"""
Утиліти для I/O — корисні при resume після перерваних запусків.

Функції:
    - is_valid_parquet(path)         — швидка перевірка parquet через read_metadata
    - phase_output_valid(path)       — перевірка + автовидалення corrupt
    - find_corrupt_parquets(root)    — пошук всіх corrupt parquet у дереві
"""

from pathlib import Path
from typing import List

import pyarrow.parquet as pq


def is_valid_parquet(path: Path) -> bool:
    """
    Швидка перевірка parquet файлу через read_metadata.

    Не читає дані, лише footer/schema. Виконується за <1ms на файл.

    Args:
        path: Шлях до parquet файлу.

    Returns:
        True якщо файл валідний parquet, False якщо corrupt/missing.
    """
    if not path.exists():
        return False
    if path.stat().st_size == 0:
        return False
    try:
        pq.read_metadata(str(path))
        return True
    except Exception:
        return False


def phase_output_valid(path: Path, auto_delete_corrupt: bool = True) -> bool:
    """
    Перевірити валідність output parquet попередньої phase.

    Якщо файл існує але corrupt (наприклад, процес вбили посеред write) —
    при `auto_delete_corrupt=True` видаляємо файл, щоб phase перерахувалась.

    Args:
        path: Шлях до parquet.
        auto_delete_corrupt: Видаляти corrupt файли (для resume safety).

    Returns:
        True якщо файл існує і валідний (можна skip phase).
        False якщо немає або corrupt (треба rerun phase).
    """
    if not path.exists():
        return False
    if is_valid_parquet(path):
        return True
    # Corrupt
    if auto_delete_corrupt:
        try:
            path.unlink()
        except Exception:
            pass
    return False


def find_corrupt_parquets(root: Path) -> List[Path]:
    """
    Знайти всі corrupt parquet файли в дереві (recursive).

    Корисно для cleanup перед запуском.

    Args:
        root: Корінь пошуку.

    Returns:
        Список шляхів до corrupt parquet файлів.
    """
    if not root.exists():
        return []
    corrupt = []
    for p in root.rglob("*.parquet"):
        if not is_valid_parquet(p):
            corrupt.append(p)
    return corrupt
