"""Intermarché : promos dans le HTML statique de /produits/, paginé via ?_pagination=N."""

import hashlib
import logging
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup, Tag

from promo_notifier.models import Promo
from promo_notifier.sources.base import PAGE_DELAY_SECONDS, TIMEOUT, parse_price

log = logging.getLogger(__name__)

BASE_URL = "https://www.intermarche.be/produits/"
MAX_PAGES = 40  # garde-fou si la pagination change

_VALIDITY_RE = re.compile(r"Valide du (\d{1,2})/(\d{1,2})(?:/(\d{4}))? au (\d{1,2})/(\d{1,2})/(\d{4})")


def parse_validity(html: str) -> tuple[date | None, date | None]:
    """'Valide du 13/10 au 18/10/2026' -> (2026-10-13, 2026-10-18)."""
    m = _VALIDITY_RE.search(html)
    if not m:
        return None, None
    d1, m1, y1, d2, m2, y2 = m.groups()
    end = date(int(y2), int(m2), int(d2))
    start_year = int(y1) if y1 else (end.year - 1 if int(m1) > end.month else end.year)
    return date(start_year, int(m1), int(d1)), end


def _text(el: Tag | None) -> str | None:
    if el is None:
        return None
    text = " ".join(el.get_text(" ", strip=True).split())
    return text or None


def _parse_card(card: Tag, valid_from: date | None, valid_to: date | None) -> Promo | None:
    paragraph = card.select_one(".card-text p")
    if paragraph is None:
        return None

    bold = paragraph.find("b")
    name = _text(bold)
    if bold is not None:
        bold.extract()
    lines = [line.strip() for line in paragraph.get_text("\n").split("\n") if line.strip()]
    if not name:
        if not lines:
            return None
        name, lines = lines[0], lines[1:]

    price_el = card.select_one(".pdw-price")
    promo_price = None
    if price_el is not None:
        sup = price_el.find("sup")
        cents = sup.get_text(strip=True) if sup else "00"
        if sup:
            sup.extract()
        promo_price = parse_price(f"{price_el.get_text(strip=True)},{cents}")

    description = " · ".join(lines) or None
    # data-reference (EAN) est parfois vide : repli sur un hash du libellé.
    ref = str(card.get("data-reference") or "").strip()
    product_id = ref or hashlib.sha1(f"{name}|{description}".encode()).hexdigest()[:12]

    img = card.select_one("img")
    return Promo(
        store="intermarche",
        product_id=product_id,
        name=name,
        description=description,
        mechanic=_text(card.select_one(".pdw-promo-banner")),
        regular_price=parse_price(_text(card.select_one(".pdw-price-stroke"))),
        promo_price=promo_price,
        unit=_text(card.select_one(".pdw-price-unit")),
        valid_from=valid_from,
        valid_to=valid_to,
        url=BASE_URL,
        image_url=str(img["src"]) if img and img.get("src") else None,
    )


def parse_page(html: str) -> list[Promo]:
    soup = BeautifulSoup(html, "html.parser")
    valid_from, valid_to = parse_validity(html)
    promos = []
    for card in soup.select(".pdw-product-item"):
        promo = _parse_card(card, valid_from, valid_to)
        # La page liste aussi des produits du folder sans réduction (prix
        # "sélection") : on ne garde que ceux avec une mécanique ou un prix barré.
        if promo and (promo.mechanic or promo.regular_price is not None):
            promos.append(promo)
    return promos


class IntermarcheSource:
    name = "intermarche"

    def fetch(self, session: requests.Session) -> list[Promo]:
        promos: dict[str, Promo] = {}
        for page in range(1, MAX_PAGES + 1):
            resp = session.get(BASE_URL, params={"_pagination": page}, timeout=TIMEOUT)
            resp.raise_for_status()
            page_promos = parse_page(resp.text)
            new = [p for p in page_promos if p.uid not in promos]
            if not new:
                break
            promos.update((p.uid, p) for p in new)
            time.sleep(PAGE_DELAY_SECONDS)
        log.info("Intermarché : %d promos sur %d page(s)", len(promos), page)
        return list(promos.values())
