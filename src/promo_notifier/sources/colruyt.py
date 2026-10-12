"""Colruyt : lecture du dépliant publié par Colruyt sur Issuu.

Le site colruyt.be protège ses promos (API à clé applicative + page anti-bot) ;
on ne le contourne pas. Colruyt publie en revanche son dépliant sur Issuu
(issuu.com/colruytgroup, téléchargement autorisé). Les pages sont des images,
lues par Claude (voir leaflet.py).

Un dépliant dure deux semaines : le résultat est mis en cache dans
state/colruyt_cache.json et l'IA n'est appelée qu'à la sortie d'un nouveau
dépliant (~37 pages, quelques centimes).
"""

import logging
import re
import time
from pathlib import Path

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

PROFILE_URL = "https://issuu.com/colruytgroup"
DOC_URL = "https://issuu.com/colruytgroup/docs/{doc}"
PAGE_IMAGE_URL = "https://image.isu.pub/{revision}/jpg/page_{page}.jpg"
# "Colruyt Meilleurs Prix - Dépliant digital" (FR, Belgique).
DOC_PREFIX = "colruyt_meilleurs_prix_-_d_pliant_d_"
MAX_PAGES = 120
CACHE_PATH = Path("state/colruyt_cache.json")


def find_latest_doc(session: requests.Session) -> tuple[str, str]:
    """Retourne (nom du document, révision) du dépliant le plus récent.

    La révision commence par un horodatage AAMMJJhhmmss : la plus grande est la plus récente."""
    resp = session.get(PROFILE_URL, timeout=TIMEOUT)
    resp.raise_for_status()
    docs = sorted(set(re.findall(rf"/colruytgroup/docs/({re.escape(DOC_PREFIX)}[a-z0-9_]+)", resp.text)))
    if not docs:
        raise SourceUnavailable("Aucun dépliant Colruyt trouvé sur Issuu")
    candidates = []
    for doc in docs:
        page = session.get(DOC_URL.format(doc=doc), timeout=TIMEOUT)
        page.raise_for_status()
        if m := re.search(r"image\.isu\.pub/(\d{12}-[0-9a-f]+)/", page.text):
            candidates.append((m.group(1), doc))
    if not candidates:
        raise SourceUnavailable("Révision du dépliant Colruyt introuvable sur Issuu")
    revision, doc = max(candidates)
    return doc, revision


class ColruytSource:
    name = "colruyt"

    def __init__(self, cache_path: Path = CACHE_PATH) -> None:
        self.cache_path = cache_path

    def fetch(self, session: requests.Session) -> list[Promo]:
        doc, revision = find_latest_doc(session)
        cache = load_cache(self.cache_path)
        if revision in cache:
            log.info("Colruyt : dépliant %s déjà analysé (cache)", doc)
            return fill_missing_dates(cache[revision])

        client = make_client()
        promos: list[Promo] = []
        page = 1
        for page in range(1, MAX_PAGES + 1):
            resp = session.get(PAGE_IMAGE_URL.format(revision=revision, page=page), timeout=TIMEOUT)
            if resp.status_code in (403, 404):  # au-delà de la dernière page
                break
            resp.raise_for_status()
            items = extract_page(client, resp.content, page, "Colruyt")
            promos.extend(to_promo(item, "colruyt", f"{DOC_URL.format(doc=doc)}/{page}") for item in items)
            log.info("Colruyt : page %d -> %d promo(s)", page, len(items))
            time.sleep(PAGE_DELAY_SECONDS)

        unique = list({p.uid: p for p in fill_missing_dates(promos)}.values())
        save_cache(self.cache_path, {revision: unique})  # seul le dépliant en cours est gardé
        log.info("Colruyt : %d promos extraites du dépliant %s (%d pages)", len(unique), doc, page - 1)
        return unique
