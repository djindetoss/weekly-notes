"""Lecture de dépliants publiés en images (Colruyt, Lidl) par Claude.

Partagé par les sources dont les promos ne sont disponibles que sous forme
de pages de dépliant : chaque page est envoyée à Claude Haiku 5.5, qui en
renvoie les promos sous forme structurée. Le résultat est mis en cache par
dépliant pour n'appeler l'IA qu'une fois par dépliant.
"""

import base64
import hashlib
import json
import logging
import os
from collections import Counter
from datetime import date
from pathlib import Path

import anthropic
from pydantic import BaseModel

from promo_notifier.models import Promo, Store
from promo_notifier.sources.base import SourceUnavailable

log = logging.getLogger(__name__)

MODEL = "claude-haiku-5-5"

PROMPT = """Voici la page {page} du dépliant promotionnel {store} (Belgique).
Extrais chaque produit en promotion visible sur cette page.

Pour chaque promo :
- brand : la marque (souvent en gras au-dessus du produit), sinon null
- name : le produit (ex. "pommes Coryphée")
- description : format, contenance, variétés, origine… sur une ligne (ex. "6 pièces · Origine : Belgique")
- mechanic : la mécanique telle qu'affichée (ex. "1+1 gratis", "-26%", "2e à -50%", "3+1 gratuit"), sinon null
- regular_price : le prix barré (prix habituel), sinon null
- promo_price : le prix promo affiché en grand pour l'article, sinon null ; ne mets pas un prix au kilo ici
- unit : le prix au kilo/litre ou l'unité affiché(e) près du prix (ex. "3,23/kg"), sinon null
- valid_from / valid_to : dates de validité au format AAAA-MM-JJ. Utilise la période propre au produit
  si elle est indiquée (bandeau de dates près du produit), sinon la période générale du dépliant
  si elle figure sur la page. L'année est {year} sauf indication contraire. Sinon null.

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


def make_client() -> anthropic.Anthropic:
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        raise SourceUnavailable("clé API Anthropic absente (secret ANTHROPIC_API_KEY)")
    return anthropic.Anthropic()


def extract_page(
    client: anthropic.Anthropic, image: bytes, page: int, store_label: str, media_type: str = "image/jpeg"
) -> list[ExtractedPromo]:
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
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image).decode("ascii"),
                        },
                    },
                    {
                        "type": "text",
                        "text": PROMPT.format(page=page, store=store_label, year=date.today().year),
                    },
                ],
            }
        ],
        output_format=PageExtraction,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        log.warning("%s : page %d non lue (stop_reason=%s)", store_label, page, response.stop_reason)
        return []
    return response.parsed_output.promos


def _parse_iso(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def to_promo(item: ExtractedPromo, store: Store, url: str) -> Promo:
    label = f"{item.brand}|{item.name}|{item.description}".casefold()
    return Promo(
        store=store,
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
        url=url,
    )


def fill_missing_dates(promos: list[Promo], default: tuple[date, date] | None = None) -> list[Promo]:
    """Applique aux promos sans dates la période connue du dépliant (`default`)
    ou, à défaut, la période la plus fréquente parmi ses promos."""
    if default is None:
        periods = Counter((p.valid_from, p.valid_to) for p in promos if p.valid_from and p.valid_to)
        if not periods:
            return promos
        default = periods.most_common(1)[0][0]
    start, end = default
    return [p if p.valid_to else p.model_copy(update={"valid_from": start, "valid_to": end}) for p in promos]


def load_cache(path: Path) -> dict[str, list[Promo]]:
    """Cache {identifiant de dépliant: promos extraites}."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return {doc: [Promo.model_validate(p) for p in promos] for doc, promos in raw["docs"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def save_cache(path: Path, docs: dict[str, list[Promo]]) -> None:
    payload = {"docs": {doc: [p.model_dump(mode="json") for p in promos] for doc, promos in docs.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
