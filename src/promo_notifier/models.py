"""Format commun d'une promotion, quelle que soit l'enseigne."""

from datetime import date
from typing import Literal

from pydantic import BaseModel

Store = Literal["intermarche", "delhaize", "colruyt", "aldi", "lidl"]

STORE_LABELS: dict[str, str] = {
    "intermarche": "Intermarché",
    "delhaize": "Delhaize",
    "colruyt": "Colruyt",
    "aldi": "Aldi",
    "lidl": "Lidl",
}


class Promo(BaseModel):
    store: Store
    product_id: str
    name: str
    brand: str | None = None
    description: str | None = None  # format, contenance, variétés…
    mechanic: str | None = None  # "1+1 GRATIS", "-25%", "2 POUR 1,80€"…
    regular_price: float | None = None
    promo_price: float | None = None
    unit: str | None = None  # "La pièce", "Les 100g"…
    valid_from: date | None = None
    valid_to: date | None = None
    url: str | None = None
    image_url: str | None = None
    discount: int | None = None  # % de réduction estimé (voir discount.py)

    @property
    def uid(self) -> str:
        """Identifiant stable d'une promo : le même produit avec la même
        mécanique sur la même période n'est notifié qu'une fois."""
        return f"{self.store}:{self.product_id}:{self.mechanic or ''}:{self.valid_to or ''}"

    @property
    def search_text(self) -> str:
        return " ".join(p for p in (self.brand, self.name, self.description) if p)
