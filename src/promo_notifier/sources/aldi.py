"""Aldi : la page /fr/offres.html contient les offres de la semaine en JSON
(__NEXT_DATA__ -> apiData -> OFFER_GET -> algoliaDataMap), avec prix barré,
prix promo, mécanique et dates de validité."""

import json
import logging
import re
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from promo_notifier.models import Promo
from promo_notifier.sources.base import TIMEOUT

log = logging.getLogger(__name__)

OFFERS_URL = "https://www.aldi.be/fr/offres.html"
PRODUCT_URL = "https://www.aldi.be/fr/product/{slug}.html"
# Étiquettes qui ne sont pas des réductions : sans prix barré, l'article n'est pas une promo.
NOT_A_DEAL = {"STOCK LIMITÉ", "XXL", "NOUVEAU"}


def _offers(html: str) -> dict[str, dict[str, Any]]:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("Aldi : données __NEXT_DATA__ introuvables")
    api_data = json.loads(json.loads(m.group(1))["props"]["pageProps"]["apiData"])
    for name, entry in api_data:
        if name == "OFFER_GET":
            return entry["res"]["algoliaDataMap"]
    raise RuntimeError("Aldi : bloc OFFER_GET introuvable")


def _promotion(product: dict[str, Any]) -> dict[str, Any]:
    """Prix promo en cours (ou le premier annoncé), avec ses dates locales."""
    promotions = product.get("promotionPrices") or []
    return promotions[0] if promotions else product.get("currentPrice") or {}


def _date(price: dict[str, Any], key: str) -> date | None:
    """Date belge d'un horodatage Aldi. "validUntil" vaut minuit le lendemain du
    dernier jour (fin exclusive) : on recule d'une seconde."""
    stamp = price.get(key)
    if not stamp:
        return None
    if key == "validUntil":
        stamp -= 1
    return datetime.fromtimestamp(stamp, ZoneInfo("Europe/Brussels")).date()


def parse_offers(html: str) -> list[Promo]:
    promos = []
    for product in _offers(html).values():
        price = _promotion(product)
        label = ((price.get("priceTagLabels") or {}).get("promoText1") or "").strip() or None
        regular = (price.get("strikePrice") or {}).get("strikePriceValue")
        if regular is None and (label is None or label.upper() in NOT_A_DEAL):
            continue
        base = (price.get("basePrice") or [{}])[0]
        unit = f"{base['basePriceValue']:.2f} € {base['basePriceScale']}".replace(".", ",") if base else None
        image = next((a["url"] for a in product.get("assets") or [] if a.get("type") == "primary"), None)
        promos.append(
            Promo(
                store="aldi",
                product_id=str(product["objectID"]),
                name=" ".join(product["name"].split()),
                brand=product.get("brandName"),
                description=product.get("salesUnit"),
                mechanic=label,
                regular_price=regular,
                promo_price=price.get("priceValue"),
                unit=unit,
                valid_from=_date(price, "validFrom"),
                valid_to=_date(price, "validUntil"),
                url=PRODUCT_URL.format(slug=product["productSlug"]) if product.get("productSlug") else None,
                image_url=image,
            )
        )
    return promos


class AldiSource:
    name = "aldi"

    def fetch(self, session: requests.Session) -> list[Promo]:
        resp = session.get(OFFERS_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        promos = parse_offers(resp.text)
        log.info("Aldi : %d promos", len(promos))
        return promos
