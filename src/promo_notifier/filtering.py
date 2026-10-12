"""Filtrage par mots-clés, insensible à la casse et aux accents.

Un mot-clé correspond au début d'un mot : "lait" trouve "Lait demi-écrémé",
"chocolat au lait" et "laitier", mais aussi "laitue" (à écarter via `exclude`).
Un mot-clé peut contenir plusieurs mots ("huile d'olive").
"""

import re
import unicodedata

from promo_notifier.models import Promo


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _pattern(keyword: str) -> re.Pattern[str]:
    return re.compile(r"\b" + re.escape(normalize(keyword.strip())))


def filter_promos(promos: list[Promo], keywords: list[str], exclude: list[str]) -> list[tuple[Promo, str]]:
    """Retourne les promos retenues avec le mot-clé qui a déclenché la correspondance."""
    include = [(k, _pattern(k)) for k in keywords if k.strip()]
    excluded = [_pattern(k) for k in exclude if k.strip()]
    matches = []
    for promo in promos:
        text = normalize(promo.search_text)
        if any(p.search(text) for p in excluded):
            continue
        hit = next((k for k, p in include if p.search(text)), None)
        if hit:
            matches.append((promo, hit))
    return matches
