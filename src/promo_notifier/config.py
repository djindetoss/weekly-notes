from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class Config(BaseModel):
    keywords: list[str] = Field(min_length=1)
    exclude: list[str] = []
    stores: dict[str, bool] = {"intermarche": True, "delhaize": True, "colruyt": False}


def load_config(path: Path) -> Config:
    with path.open(encoding="utf-8") as f:
        return Config.model_validate(yaml.safe_load(f))
