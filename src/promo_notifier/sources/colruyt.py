"""Colruyt : lecture du dépliant publié par Colruyt sur Issuu.

Le site colruyt.be protège ses promos (API à clé applicative + page anti-bot) ;
on ne le contourne pas. Colruyt publie en revanche son dépliant sur Issuu
(issuu.com/colruytgroup, téléchargement autorisé). Les pages sont des images :
Claude (Haiku 5.5) en extrait les promos sous forme structurée.

Un dépliant dure deux semaines : le résultat est mis en cache dans
state/colruyt_cache.json et l'IA n'est appelée qu'à la sortie d'un nouveau
dépliant (~37 pages, quelques centimes).
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
from datetime import date
from pathlib import Path

import anthropic
import requests
from pydantic import BaseModel

from promo_notifier.models import Promo
from promo_notifier.sources.base import PAGE_DELAY_SECONDS, TIMEOUT, SourceUnavailable

log = logging.getLogger(__name__)

PROFILE_URL = "https://issuu.com/colruytgroup"
DOC_URL = "https://issuu.com/colruytgroup/docs/{doc}"
PAGE_IMAGE_URL = "https://image.isu.pub/{revision}/jpg/page_{page}.jpg"
# "Colruyt Meilleurs Prix - Dépliant digital" (FR, Belgique).
DOC_PREFIX = "colruyt_meilleurs_prix_-_d_pliant_d_"
MAX_PAGES = 120
MODEL = "claude-haiku-5-5"
CACHE_PATH = Path("state/colruyt_cache.json")

PROMPT = """Voici la page {page} du dépliant promotionnel Colruyt (Belgique).
Extrais chaque produit en promotion visible sur cette page.

Pour chaque promo :
- brand : la marque (en gras au-dessus du produit, ex. "Boni Selection"), sinon null
- name : le produit (ex. "pommes Coryphée")
- description : format, contenance, variétés, origine… sur une ligne (ex. "6 pièces · Origine : Belgique")
- mechanic : la mécanique telle qu'affichée (ex. "1+1 gratis", "-26%", "2e à -50%", "3+1 gratis"), sinon null
- regular_price : le prix barré (prix habituel), sinon null
- promo_price : le prix promo affiché en grand pour l'article, sinon null ; ne mets pas un prix au kilo ici
- unit : le prix au kilo/litre ou l'unité affiché(e) près du prix (ex. "3,23/kg"), sinon null
- valid_from / valid_to : dates de validité au format AAAA-MM-JJ. Utilise la période propre au produit
  si elle est indiquée (ex. bandeau "Mer. 14/10 ▶ Mar. 20/10 incl."), sinon la période générale du
  dépliant (pied de page "Offres valables du … au …"). Déduis l'année du pied de page.

Ignore les pages sans promotion produit (couverture, recettes, conditions) : renvoie une liste vide.
N'invente rien : un champ illisible vaut null."""


class ExtractedPromo(BaseModel):
    brand: str | None
    name: str
    description: str | None
    mechanic: str | None
    regular_price: float | None
    promo_price: float | None
    unit: str | None
    valid_from: str | None
    valid_to: str | None


class PageExtraction(BaseModel):
    promos: list[ExtractedPromo]


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


def _parse_iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def to_promo(item: ExtractedPromo, doc: str, page: int) -> Promo:
    label = f"{item.brand}|{item.name}|{item.description}".casefold()
    return Promo(
        store="colruyt",
        product_id=hashlib.sha1(label.encode()).hexdigest()[:12],
        name=item.name,
        brand=item.brand,
        description=item.description,
        mechanic=item.mechanic,
        regular_price=item.regular_price,
        promo_price=item.promo_price,
        unit=item.unit,
        valid_from=_parse_iso(item.valid_from),
        valid_to=_parse_iso(item.valid_to),
        url=f"{DOC_URL.format(doc=doc)}/{page}",
    )


def extract_page(client: anthropic.Anthropic, image: bytes, page: int) -> list[ExtractedPromo]:
    response = client.messages.parse(
        model=MODEL,
        max_tokens=16000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        },
                    },
                    {"type": "text", "text": PROMPT.format(page=page)},
                ],
            }
        ],
        output_format=PageExtraction,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("Colruyt : page %d non lue (stop_reason=%s)", page, response.stop_reason)
        return []
    return response.parsed_output.promos


def _load_cache(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


class ColruytSource:
    name = "colruyt"

    def __init__(self, cache_path: Path = CACHE_PATH) -> None:
        self.cache_path = cache_path

    def fetch(self, session: requests.Session) -> list[Promo]:
        doc, revision = find_latest_doc(session)
        cache = _load_cache(self.cache_path)
        if cache and cache.get("revision") == revision:
            log.info("Colruyt : dépliant %s déjà analysé (cache)", doc)
            return [Promo.model_validate(p) for p in cache["promos"]]

        if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
            raise SourceUnavailable("clé API Anthropic absente (secret ANTHROPIC_API_KEY)")
        client = anthropic.Anthropic()

        promos: list[Promo] = []
        for page in range(1, MAX_PAGES + 1):
            resp = session.get(PAGE_IMAGE_URL.format(revision=revision, page=page), timeout=TIMEOUT)
            if resp.status_code in (403, 404):  # au-delà de la dernière page
                break
            resp.raise_for_status()
            items = extract_page(client, resp.content, page)
            promos.extend(to_promo(item, doc, page) for item in items)
            log.info("Colruyt : page %d -> %d promo(s)", page, len(items))
            time.sleep(PAGE_DELAY_SECONDS)

        unique = list({p.uid: p for p in promos}.values())
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(
            json.dumps(
                {"doc": doc, "revision": revision, "promos": [p.model_dump(mode="json") for p in unique]},
                ensure_ascii=False,
                indent=1,
            )
            + "\n",
            encoding="utf-8",
        )
        log.info("Colruyt : %d promos extraites du dépliant %s (%d pages)", len(unique), doc, page - 1)
        return unique
