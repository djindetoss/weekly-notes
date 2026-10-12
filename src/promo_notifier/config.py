from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel):
    keywords: list[str] = Field(min_length=1)
    exclude: list[str] = []
    # Promos mises en avant ("À ne pas rater") à partir de ce % de réduction.
    highlight_min_discount: int = Field(default=40, ge=1, le=99)
    # Adresse de la page filtrable (GitHub Pages), ajoutée en lien dans le mail.
    page_url: str | None = None
    stores: dict[str, bool] = {
        "intermarche": True, "delhaize": True, "colruyt": True, "aldi": True, "lidl": True
    }


def load_config(path: Path) -> Config:
    with path.open(encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
