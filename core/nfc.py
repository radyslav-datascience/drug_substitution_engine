# =============================================================================
# NFC COMPATIBILITY - drug_substitution_engine
# =============================================================================
# Файл: core/nfc.py
# Дата: 2026-04-28 (v2 — dynamic config from data/master/nfc1_config.json)
# Опис: Матриця сумісності форм випуску NFC1 для substitute identification (Phase A3).
# =============================================================================

"""
Матриця клінічної сумісності NFC1.

V2 (2026-04-28):
    - Список усіх категорій НЕ hardcoded — читається з data/master/nfc1_config.json,
      який накопичує категорії з усіх вхідних датасетів (master data).
    - Бізнес-правила (compatibility_groups, excluded) — у тому ж JSON, редагуються
      людиною. Discovery скрипт їх НЕ перезаписує.
    - Невідома категорія (вперше зустрінута, ще не в JSON) — поводиться як
      standalone (замінюється тільки сама на себе) + warning у лог.

БІЗНЕС-ПРАВИЛО (поточне):
    - Compatibility group "ORAL_SOLID_RETARD":
        Пероральні тверді звичайні ↔ Пероральні тверді тривалої дії
    - Усі інші форми — exact match (на себе) — це default поведінка для будь-якої
      форми, що не входить в жодну compatibility_group.
    - "Не предназначенные для использования у человека и прочие" — у excluded.

Використання:
    from core.nfc import is_compatible, get_compatibility_group, NFC_CONFIG
"""

import json
import logging
from pathlib import Path
from typing import Dict, Set

from config.paths import NFC1_CONFIG_PATH

log = logging.getLogger(__name__)


# =============================================================================
# CONFIG LOADER (lazy, cached at module-level)
# =============================================================================

class NFCConfig:
    """
    Конфіг сумісності NFC1, завантажений з JSON. Lazy-loaded singleton.

    Атрибути:
        all_categories:   set[str] — усі відомі категорії (накопичений master).
        excluded:         set[str] — категорії, що виключаються з аналізу.
        groups_by_form:   dict[str, str] — {form → group_name}, для O(1) lookup.

    При відсутності JSON-файлу — fallback на консервативний default
    (exact-match для всього). Це безпечно для першого запуску, коли discovery
    ще не виконувався.
    """

    def __init__(self, config_path: Path = NFC1_CONFIG_PATH):
        self.config_path:    Path        = config_path
        self.all_categories: Set[str]    = set()
        self.excluded:       Set[str]    = set()
        self.groups_by_form: Dict[str, str] = {}
        self._warned_unknown: Set[str]   = set()  # avoid spam-warning the same form
        self._loaded:        bool        = False
        self._raw:           Dict        = {}

    def load(self) -> None:
        """Завантажити JSON. Якщо файлу немає — лишити порожній стан з warning."""
        if self._loaded:
            return
        if not self.config_path.exists():
            log.warning(
                f"nfc1_config.json не знайдено: {self.config_path}. "
                f"is_compatible() працюватиме у fallback-режимі (exact-match для всіх форм). "
                f"Запустіть discover_markets для генерації."
            )
            self._loaded = True
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            self._raw = json.load(f)

        self.all_categories = set(self._raw.get("all_categories", []))
        self.excluded       = set(self._raw.get("excluded", []))

        # Розгорнути compatibility_groups у lookup-таблицю
        self.groups_by_form = {}
        for grp in self._raw.get("compatibility_groups", []):
            grp_name = grp.get("name", "UNNAMED")
            for form in grp.get("members", []):
                self.groups_by_form[form] = grp_name

        self._loaded = True
        log.info(
            f"NFCConfig loaded: {len(self.all_categories)} categories, "
            f"{len(self._raw.get('compatibility_groups', []))} compatibility groups, "
            f"{len(self.excluded)} excluded"
        )

    def warn_unknown(self, form: str) -> None:
        """Попередити лог про невідому категорію (один раз на форму)."""
        if form in self._warned_unknown:
            return
        self._warned_unknown.add(form)
        log.warning(
            f"NFC1 category '{form}' не знайдено у nfc1_config.json. "
            f"Розглядається як standalone (exact-match only). "
            f"Якщо це нова категорія — додайте її в data/master/nfc1_config.json вручну "
            f"(або re-run discover_markets для авто-додавання у all_categories)."
        )


# Module-level singleton
NFC_CONFIG = NFCConfig()


# =============================================================================
# COMPATIBILITY FUNCTIONS
# =============================================================================

def is_compatible(form_a: str, form_b: str) -> bool:
    """
    Перевірка клінічної сумісності двох форм випуску NFC1.

    Правила (у порядку перевірки):
        0. Будь-яка з форм у excluded → False.
        1. Exact match (form_a == form_b) → True.
        2. Обидві в одній compatibility_group → True.
        3. Інше → False (включно з невідомими формами — вони стають standalone).

    Args:
        form_a: NFC1_ID першого препарату.
        form_b: NFC1_ID другого препарату.

    Returns:
        True якщо форми клінічно взаємозамінні.

    Examples:
        >>> # При завантаженому конфігу з ORAL_SOLID_RETARD групою:
        >>> is_compatible("Пероральные твердые обычные", "Пероральные твердые длительно действующие")
        True
        >>> is_compatible("Пероральные твердые обычные", "Пероральные жидкие обычные")
        False  # рідкі тепер окремо
        >>> is_compatible("Парентеральные обычные", "Парентеральные обычные")
        True
    """
    NFC_CONFIG.load()

    if form_a in NFC_CONFIG.excluded or form_b in NFC_CONFIG.excluded:
        return False

    if form_a == form_b:
        return True

    grp_a = NFC_CONFIG.groups_by_form.get(form_a)
    grp_b = NFC_CONFIG.groups_by_form.get(form_b)

    # Якщо одна з форм невідома (не в groups і не в all_categories) — попередити
    if form_a not in NFC_CONFIG.all_categories:
        NFC_CONFIG.warn_unknown(form_a)
    if form_b not in NFC_CONFIG.all_categories:
        NFC_CONFIG.warn_unknown(form_b)

    # Сумісність через групу (тільки якщо обидві в одній named групі)
    if grp_a is not None and grp_a == grp_b:
        return True

    return False


def get_compatibility_group(form: str) -> str:
    """
    Визначити групу сумісності для форми випуску.

    Returns:
        Назва compatibility_group ('ORAL_SOLID_RETARD' тощо), 'EXACT_MATCH'
        для форм, що замінюються тільки самі на себе, або 'EXCLUDED'.
    """
    NFC_CONFIG.load()
    if form in NFC_CONFIG.excluded:
        return "EXCLUDED"
    grp = NFC_CONFIG.groups_by_form.get(form)
    if grp is not None:
        return grp
    return "EXACT_MATCH"


# =============================================================================
# SELF-TEST
# =============================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("=" * 60)
    print("NFC COMPATIBILITY (v2) - drug_substitution_engine")
    print("=" * 60)
    print(f"\nConfig path: {NFC1_CONFIG_PATH}")
    print(f"Exists:      {NFC1_CONFIG_PATH.exists()}")

    NFC_CONFIG.load()

    print(f"\nLoaded:")
    print(f"  all_categories:        {len(NFC_CONFIG.all_categories)}")
    print(f"  excluded:              {len(NFC_CONFIG.excluded)}")
    print(f"  compatibility_groups:  {len(NFC_CONFIG._raw.get('compatibility_groups', []))}")

    print("\nCompatibility groups:")
    for grp in NFC_CONFIG._raw.get("compatibility_groups", []):
        print(f"  [{grp.get('name')}]")
        for m in grp.get("members", []):
            print(f"    + {m}")

    print("\nExcluded:")
    for f in NFC_CONFIG.excluded:
        print(f"  x {f}")

    # Тести (працюють лише якщо JSON завантажено з реальними даними)
    if NFC_CONFIG.all_categories:
        print("\nis_compatible() examples:")
        tests = [
            ("Пероральные твердые обычные", "Пероральные твердые длительно действующие", True),
            ("Пероральные твердые обычные", "Пероральные жидкие обычные",                False),
            ("Пероральные твердые обычные", "Парентеральные обычные",                    False),
            ("Парентеральные обычные",      "Парентеральные обычные",                    True),
            ("Офтальмологические",          "Ректальные системные",                      False),
        ]
        all_ok = True
        for a, b, expected in tests:
            actual = is_compatible(a, b)
            ok = "OK" if actual == expected else "FAIL"
            if actual != expected:
                all_ok = False
            a_short = a[:30] + "..." if len(a) > 33 else a
            b_short = b[:30] + "..." if len(b) > 33 else b
            print(f"  [{ok}] {a_short:<33} + {b_short:<33} = {actual}")
        print(f"\nValidation: {'PASSED' if all_ok else 'FAILED'}")
    else:
        print("\nNo config loaded - run discover_markets first.")
