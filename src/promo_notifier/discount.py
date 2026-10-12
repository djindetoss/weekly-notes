"""Estimation du pourcentage de réduction réel d'une promo.

Ordre de priorité :
1. prix habituel et prix promo connus -> calcul direct ;
2. sinon, lecture de la mécanique : "1+1 gratis" = 50 %, "2e à -50%" = 25 %,
   "-30%" = 30 %, "3 pour €5" avec le prix unitaire habituel…
Retourne None quand la réduction ne peut pas être estimée.
"""

import re

from promo_notifier.filtering import normalize
from promo_notifier.models import Promo

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"\s*(?:kg|g|l|cl|ml)?\s*"
_GRATIS = re.compile(_NUM + _UNIT + r"\+\s*" + _NUM + _UNIT + "(?:gratis|gratuit)")
_NTH = re.compile(r"(\d+)\s*(?:e|eme|ieme)\s*a\s*-?\s*(\d+)\s*%")
_PERCENT = re.compile(r"-\s*(\d+)\s*%")
_N_FOR = re.compile(r"(\d+)\s*pour\s*€?\s*" + _NUM)


def _num(text: str) -> float:
    return float(text.replace(",", "."))


def _from_mechanic(mechanic: str, regular_price: float | None) -> float | None:
    text = normalize(mechanic)
    if m := _GRATIS.search(text):
        paid, free = _num(m.group(1)), _num(m.group(2))
        return 100 * free / (paid + free)
    if m := _NTH.search(text):
        nth, pct = int(m.group(1)), int(m.group(2))
        return pct / nth if nth else None
    if m := _PERCENT.search(text):
        return float(m.group(1))
    if (m := _N_FOR.search(text)) and regular_price:
        count, total = int(m.group(1)), _num(m.group(2))
        if count:
            return 100 * (1 - total / (count * regular_price))
    return None


def estimate_discount(promo: Promo) -> int | None:
    if promo.regular_price and promo.promo_price is not None and promo.promo_price < promo.regular_price:
        pct = 100 * (1 - promo.promo_price / promo.regular_price)
    elif promo.mechanic:
        pct = _from_mechanic(promo.mechanic, promo.regular_price)
    else:
        pct = None
    if pct is None or not 0 < pct < 100:
        return None
    return round(pct)
