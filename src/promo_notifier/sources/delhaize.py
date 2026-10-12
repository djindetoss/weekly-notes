"""Delhaize : endpoint GraphQL interne (persisted query "ProductList") utilisé
par la page /fr/promotions. Pas besoin de navigateur.

Si Delhaize redéploie son front, le hash de la requête peut changer : le
retrouver dans l'onglet Réseau du navigateur sur /fr/promotions
(requête api/v1/?operationName=ProductList).
"""

import json
import logging
import time
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

from promo_notifier.models import Promo
from promo_notifier.sources.base import PAGE_DELAY_SECONDS, TIMEOUT, parse_price

log = logging.getLogger(__name__)

API_URL = "https://www.delhaize.be/api/v1/"
SITE_URL = "https://www.delhaize.be"
QUERY_HASH = "ef54fc2d8da4a9ad4987b2fb18f61c59f341d018be0f4670b0c9c7dabff07e5c"
PAGE_SIZE = 50  # au-delà, l'API répond 500
MAX_PAGES = 100
# L'API refuse les requêtes GET sans ces en-têtes (protection CSRF d'Apollo).
APOLLO_HEADERS = {
    "Accept": "application/json",
    "apollographql-client-name": "be-dll-web-stores",
    "apollographql-client-version": "1.0",
    "x-apollo-operation-name": "ProductList",
}
BRUSSELS = ZoneInfo("Europe/Brussels")


def _variables(page: int) -> dict[str, Any]:
    return {
        "productListingType": "PROMOTION_SEARCH",
        "lang": "fr",
        "productCodes": "",
        "categoryCode": "",
        "excludedProductCodes": "",
        "brands": "",
        "keywords": "",
        "productTypes": "",
        "lazyLoadCount": PAGE_SIZE,
        "pageNumber": page,
        "sort": "categoryOrder",
        "searchQuery": "",
        "hideProductsWithoutPromo": False,
        "hideUnavailableProducts": True,
        "maxItemsToDisplay": 0,
        "includePotentialActivatableOffers": True,
        "customerSegment": "newPromoPageSegment",
    }


def _parse_date(value: str | None) -> date | None:
    """'14/10/2026 21:59:00' (UTC) -> date locale belge."""
    if not value:
        return None
    try:
        utc = datetime.strptime(value, "%d/%m/%Y %H:%M:%S").replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        return None
    return utc.astimezone(BRUSSELS).date()


def parse_products(payload: dict[str, Any]) -> list[Promo]:
    promos = []
    for product in payload["data"]["productList"]["products"]:
        promotion = next((p for p in product.get("potentialPromotions") or [] if p.get("toDisplay")), None)
        if promotion is None:
            continue
        price = product.get("price") or {}
        regular = price.get("value")
        discounted = parse_price(price.get("discountedPriceFormatted"))
        image = next((i["url"] for i in product.get("images") or [] if i.get("format") == "respListGrid"), None)
        promos.append(
            Promo(
                store="delhaize",
                product_id=product["code"],
                name=" ".join(product["name"].split()),
                brand=product.get("manufacturerName"),
                description=price.get("supplementaryPriceLabel2"),
                mechanic=promotion.get("description") or promotion.get("title"),
                regular_price=regular,
                promo_price=discounted if discounted is not None and discounted != regular else None,
                unit=price.get("supplementaryPriceLabel1"),
                valid_from=_parse_date(promotion.get("startDate")),
                valid_to=_parse_date(promotion.get("endDate")),
                url=SITE_URL + product["url"] if product.get("url") else None,
                image_url=SITE_URL + image if image else None,
            )
        )
    return promos


class DelhaizeSource:
    name = "delhaize"

    def fetch(self, session: requests.Session) -> list[Promo]:
        promos: dict[str, Promo] = {}
        extensions = json.dumps({"persistedQuery": {"version": 1, "sha256Hash": QUERY_HASH}})
        total_pages = 1
        page = 0
        while page < min(total_pages, MAX_PAGES):
            resp = session.get(
                API_URL,
                params={
                    "operationName": "ProductList",
                    "variables": json.dumps(_variables(page)),
                    "extensions": extensions,
                },
                headers=APOLLO_HEADERS,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            payload = resp.json()
            if "errors" in payload:
                raise RuntimeError(f"Erreur GraphQL Delhaize : {payload['errors']}")
            total_pages = payload["data"]["productList"]["pagination"]["totalPages"]
            promos.update((p.uid, p) for p in parse_products(payload))
            page += 1
            time.sleep(PAGE_DELAY_SECONDS)
        log.info("Delhaize : %d promos sur %d page(s)", len(promos), page)
        return list(promos.values())
