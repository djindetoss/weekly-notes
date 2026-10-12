"""Lidl : lecture du dépliant hebdomadaire publié par Lidl (folder-fr.lidl.be).

Les promos alimentaires de la semaine ne sont pas en ligne sous forme de
données produits ; Lidl publie en revanche son dépliant (téléchargement
autorisé) via l'API publique de sa visionneuse, qui donne les dates et les
images des pages. Les pages sont lues par Claude (voir leaflet.py).

Le dépliant de la semaine suivante est souvent publié à l'avance : tous les
dépliants "fr-folder-*" pas encore terminés sont traités. Chaque dépliant
n'est analysé qu'une fois (cache state/lidl_cache.json, ~36 pages).
"""

import logging
import re
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

from promo_notifier.models import Promo
from promo_notifier.sources.base import PAGE_DELAY_SECONDS, TIMEOUT, SourceUnavailable
from promo_notifier.sources.leaflet import (
    extract_page,
    fill_missing_dates,
    load_cache,
    make_client,
    save_cache,
    to_promo,
)

log = logging.getLogger(__name__)

LEAFLETS_PAGE = "https://www.lidl.be/c/fr-BE/depliants-et-magazines/s10008101"
FLYER_API = "https://endpoints.leaflets.schwarz/v4/flyer"
FLYER_ID_RE = re.compile(r"https://folder-fr\.lidl\.be/(fr-folder-[a-z0-9-]+)")
CACHE_PATH = Path("state/lidl_cache.json")


def find_flyers(session: requests.Session) -> list[str]:
    resp = session.get(LEAFLETS_PAGE, timeout=TIMEOUT)
    resp.raise_for_status()
    flyers = sorted(set(FLYER_ID_RE.findall(resp.text)))
    if not flyers:
        raise SourceUnavailable("Aucun dépliant Lidl trouvé")
    return flyers


def get_flyer(session: requests.Session, identifier: str) -> dict[str, Any]:
    resp = session.get(FLYER_API, params={"flyer_identifier": identifier, "region_id": 0}, timeout=TIMEOUT)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("success"):
        raise RuntimeError(f"Dépliant Lidl {identifier} : {payload.get('message')}")
    return payload["flyer"]


def flyer_period(flyer: dict[str, Any]) -> tuple[date, date]:
    return (
        date.fromisoformat(flyer.get("offerStartDate") or flyer["startDate"]),
        date.fromisoformat(flyer.get("offerEndDate") or flyer["endDate"]),
    )


class LidlSource:
    name = "lidl"

    def __init__(self, cache_path: Path = CACHE_PATH) -> None:
        self.cache_path = cache_path

    def _extract(self, session: requests.Session, flyer: dict[str, Any], identifier: str) -> list[Promo]:
        client = make_client()
        promos: list[Promo] = []
        for page in flyer["pages"]:
            number = page["number"]
            resp = session.get(page["image"], timeout=TIMEOUT)
            resp.raise_for_status()
            items = extract_page(client, resp.content, number, "Lidl")
            url = f"https://folder-fr.lidl.be/{identifier}/page/{number}"
            promos.extend(to_promo(item, "lidl", url) for item in items)
            log.info("Lidl : %s page %d -> %d promo(s)", identifier, number, len(items))
            time.sleep(PAGE_DELAY_SECONDS)
        return list({p.uid: p for p in fill_missing_dates(promos, flyer_period(flyer))}.values())

    def fetch(self, session: requests.Session) -> list[Promo]:
        cache = load_cache(self.cache_path)
        kept: dict[str, list[Promo]] = {}
        today = date.today()
        for identifier in find_flyers(session):
            flyer = get_flyer(session, identifier)
            if flyer_period(flyer)[1] < today:
                continue
            flyer_id = flyer["id"]
            if flyer_id in cache:
                log.info("Lidl : dépliant %s déjà analysé (cache)", identifier)
                kept[flyer_id] = cache[flyer_id]
            else:
                kept[flyer_id] = self._extract(session, flyer, identifier)
                save_cache(self.cache_path, {**cache, **kept})  # sauvegarde après chaque dépliant
        save_cache(self.cache_path, kept)  # oublie les dépliants terminés
        promos = [p for flyer_promos in kept.values() for p in flyer_promos]
        log.info("Lidl : %d promos sur %d dépliant(s)", len(promos), len(kept))
        return promos
