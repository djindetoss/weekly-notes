"""Page web statique et filtrable de toutes les promos de la semaine
(publiée par GitHub Pages). Les données sont intégrées en JSON dans la page."""

import json
from datetime import datetime
from importlib.resources import files
from pathlib import Path
from zoneinfo import ZoneInfo

from promo_notifier.models import STORE_LABELS, Promo


def build_page(
    promos: list[Promo],
    keywords: dict[str, str],
    new_uids: set[str],
    stores: list[str],
    min_discount: int,
) -> str:
    """`keywords` associe l'uid d'une promo au mot-clé qui l'a retenue."""
    data = {
        "generated": datetime.now(ZoneInfo("Europe/Brussels")).strftime("%d/%m/%Y à %H:%M"),
        "highlight": min_discount,
        "stores": {s: STORE_LABELS[s] for s in stores},
        "promos": [
            {
                **promo.model_dump(mode="json", exclude={"product_id"}),
                "keyword": keywords.get(promo.uid),
                "is_new": promo.uid in new_uids,
            }
            for promo in promos
        ],
    }
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    template = files("promo_notifier").joinpath("page_template.html").read_text(encoding="utf-8")
    return template.replace("/*DATA*/", payload)


def write_page(path: Path, html: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
