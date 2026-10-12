"""Carrefour : folders Hypermarché et Market republiés par myShopi.

carrefour.be est protégé par Cloudflare (pas de contournement). Les folders
officiels sont republiés par myShopi (myshopi.com, robots autorisés), avec
leurs dates et les images des pages, lues par Claude (voir leaflet.py).

Carrefour publie chaque semaine un folder Hypermarché valable deux semaines,
et un folder Market valable une semaine. Les catalogues thématiques, plus
longs, sont ignorés. Chaque folder n'est analysé qu'une fois
(cache state/carrefour_cache.json).
"""

import json
import logging
import re
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from promo_notifier.models import Promo
from promo_notifier.sources.base import PAGE_DELAY_SECONDS, TIMEOUT, get_with_retry
from promo_notifier.sources.leaflet import (
    extract_page,
    fill_missing_dates,
    load_cache,
    make_client,
    save_cache,
    to_promo,
)

log = logging.getLogger(__name__)

BASE_URL = "https://www.myshopi.com/fr"
# (enseigne myShopi, libellé pour l'IA, durée maximale d'un folder promo en jours)
SHOPS = [("carrefour", "Carrefour Hypermarché", 16), ("carrefour-market", "Carrefour Market", 8)]
CACHE_PATH = Path("state/carrefour_cache.json")
BRUSSELS = ZoneInfo("Europe/Brussels")


def _local_date(value: str) -> date:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(BRUSSELS).date()


def find_folders(session: requests.Session, shop: str) -> list[str]:
    resp = session.get(f"{BASE_URL}/{shop}/folder-offres", timeout=TIMEOUT)
    resp.raise_for_status()
    return sorted(set(re.findall(rf"/fr/{re.escape(shop)}-folder/([0-9a-f-]{{36}})/", resp.text)))


def get_folder(session: requests.Session, shop: str, folder_id: str) -> dict[str, Any]:
    """Métadonnées (dates) et pages d'un folder, depuis les données Nuxt de la page myShopi."""
    resp = session.get(f"{BASE_URL}/{shop}-folder/{folder_id}/0", timeout=TIMEOUT)
    resp.raise_for_status()
    m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', resp.text, re.S)
    if not m:
        raise RuntimeError(f"myShopi : données du folder {folder_id} introuvables")
    entries = [json.loads(s) for s in json.loads(m.group(1)) if isinstance(s, str) and s.startswith("{")]
    brochure = next(e["brochure"] for e in entries if "brochure" in e)
    pages = next(e["pages"] for e in entries if "pages" in e)
    return {
        "id": folder_id,
        "start": _local_date(brochure["activeFrom"]),
        "end": _local_date(brochure["expireAfter"]),
        "pages": sorted(pages, key=lambda p: p["index"]),
    }


class CarrefourSource:
    name = "carrefour"

    def __init__(self, cache_path: Path = CACHE_PATH) -> None:
        self.cache_path = cache_path

    def _extract(self, session: requests.Session, shop: str, label: str, folder: dict[str, Any]) -> list[Promo]:
        client = make_client()
        promos: list[Promo] = []
        for page in folder["pages"]:
            number = page["index"] + 1
            resp = get_with_retry(session, page["image_large"])
            resp.raise_for_status()
            items = extract_page(client, resp.content, number, label, media_type="image/webp")
            url = f"{BASE_URL}/{shop}-folder/{folder['id']}/{page['index']}"
            promos.extend(to_promo(item, "carrefour", url) for item in items)
            log.info("%s : folder %s page %d -> %d promo(s)", label, folder["id"][:8], number, len(items))
            time.sleep(PAGE_DELAY_SECONDS)
        period = (folder["start"], folder["end"])
        return list({p.uid: p for p in fill_missing_dates(promos, period)}.values())

    def fetch(self, session: requests.Session) -> list[Promo]:
        cache = load_cache(self.cache_path)
        kept: dict[str, list[Promo]] = {}
        today = date.today()
        for shop, label, max_days in SHOPS:
            for folder_id in find_folders(session, shop):
                folder = get_folder(session, shop, folder_id)
                # Terminé (ou dernier jour : inutile de l'analyser), ou catalogue thématique.
                if folder["end"] <= today or (folder["end"] - folder["start"]).days > max_days:
                    continue
                if folder_id in cache:
                    log.info("%s : folder %s déjà analysé (cache)", label, folder_id[:8])
                    kept[folder_id] = cache[folder_id]
                else:
                    kept[folder_id] = self._extract(session, shop, label, folder)
                    save_cache(self.cache_path, {**cache, **kept})  # sauvegarde après chaque folder
                time.sleep(PAGE_DELAY_SECONDS)
        save_cache(self.cache_path, kept)  # oublie les folders terminés
        promos = [p for folder_promos in kept.values() for p in folder_promos]
        log.info("Carrefour : %d promos sur %d folder(s)", len(promos), len(kept))
        return promos
