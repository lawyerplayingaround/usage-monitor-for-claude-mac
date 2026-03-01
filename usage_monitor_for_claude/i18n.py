"""
Internationalization
=====================

Loads translations for the detected system language with English fallback.
"""
from __future__ import annotations

import json
import locale
from pathlib import Path
from typing import Any

LOCALE_DIR = Path(__file__).parent.parent / 'locale'


def detect_lang_code(lang: str) -> str:
    """Detect locale file code from system locale string using convention-based lookup.

    Lookup chain: ``{lang}-{REGION}.json`` → ``{lang}.json`` → ``en.json``.
    No mapping required - the locale directory structure *is* the configuration.

    Parameters
    ----------
    lang : str
        System locale string, e.g. ``'de_DE'`` or ``'German_Germany'``.

    Returns
    -------
    str
        Locale file code (without ``.json``).
    """
    normalized = locale.normalize(lang).split('.')[0]
    parts = normalized.split('_', 1)
    base = parts[0].lower()

    # locale.normalize() doesn't resolve all Windows names (e.g. 'Spanish_Mexico').
    # If the base is not a short ISO 639 code, retry with just the language word.
    if len(base) > 3:
        base = locale.normalize(parts[0]).split('.')[0].split('_')[0].lower()

    region = parts[1] if len(parts) > 1 and len(base) <= 3 else ''

    if region and (LOCALE_DIR / f'{base}-{region}.json').exists():
        return f'{base}-{region}'
    if (LOCALE_DIR / f'{base}.json').exists():
        return base

    return 'en'


def load_translations() -> dict[str, Any]:
    """Load translations for the detected system language, fallback to English."""
    lang = locale.getlocale()[0] or ''
    lang_code = detect_lang_code(lang)

    return json.loads((LOCALE_DIR / f'{lang_code}.json').read_text(encoding='utf-8'))


T: dict[str, Any] = load_translations()
