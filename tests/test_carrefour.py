import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from promo_notifier.sources import carrefour
from promo_notifier.sources.leaflet import ExtractedPromo, load_cache

WEEKLY = "9f55ed4b-fc62-40b5-ade0-84659c4f61da"
CATALOGUE = "4135ebd7-3e47-4b4d-ad70-034564ddadff"
MARKET = "ee78427d-f350-4dc1-9616-ecde2b472b95"
ENDS_TODAY = "7f6ee379-eff8-4118-8a13-ea5278d36e53"

FOLDERS = {  # id: (début UTC, fin UTC)
    WEEKLY: ("2026-10-13T22:00:00Z", "2026-10-26T22:59:00Z"),
    CATALOGUE: ("2026-10-13T22:00:00Z", "2026-12-06T22:59:00Z"),
    MARKET: ("2026-10-13T22:00:00Z", "2026-10-20T21:59:00Z"),
    ENDS_TODAY: ("2026-09-29T22:00:00Z", "2026-10-13T21:59:00Z"),
}


def nuxt_page(folder_id: str) -> str:
    start, end = FOLDERS[folder_id]
    brochure = json.dumps({"brochure": {"activeFrom": start, "expireAfter": end, "id": folder_id}})
    pages = json.dumps({"pages": [{"index": 0, "image_large": f"https://cdn/{folder_id}/0.webp"}]})
    return f'<script type="application/json" id="__NUXT_DATA__">{json.dumps([{"x": 1}, brochure, pages])}</script>'


class FakeResponse:
    def __init__(self, text: str = "") -> None:
        self.text, self.content = text, text.encode()

    status_code = 200

    def raise_for_status(self) -> None:
        pass


class FakeSession:
    def get(self, url: str, **_: Any) -> FakeResponse:
        if url.endswith("/carrefour/folder-offres"):
            ids = [WEEKLY, CATALOGUE, ENDS_TODAY]
            return FakeResponse("".join(f'<a href="/fr/carrefour-folder/{i}/0">' for i in ids))
        if url.endswith("/carrefour-market/folder-offres"):
            return FakeResponse(f'<a href="/fr/carrefour-market-folder/{MARKET}/3?offer=x">')
        for folder_id in FOLDERS:
            if url.endswith(f"-folder/{folder_id}/0"):
                return FakeResponse(nuxt_page(folder_id))
        return FakeResponse("image")


def test_carrefour_keeps_weekly_folders(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls) -> "FakeDate":
            return cls(2026, 10, 13)

    monkeypatch.setattr(carrefour, "date", FakeDate)
    monkeypatch.setattr(carrefour, "PAGE_DELAY_SECONDS", 0)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    seen: list[tuple[str, str]] = []

    def fake_extract(client: object, image: bytes, page: int, store: str, media_type: str) -> list[ExtractedPromo]:
        seen.append((store, media_type))
        return [ExtractedPromo(brand="Barilla", name=f"pâtes {store}", description=None, mechanic="3+3 gratis",
                               regular_price=None, promo_price=None, unit=None, valid_from=None, valid_to=None)]

    monkeypatch.setattr(carrefour, "extract_page", fake_extract)
    cache = tmp_path / "carrefour_cache.json"
    promos = carrefour.CarrefourSource(cache).fetch(FakeSession())  # type: ignore[arg-type]

    assert seen == [("Carrefour Hypermarché", "image/webp"), ("Carrefour Market", "image/webp")]
    assert sorted(load_cache(cache)) == sorted([WEEKLY, MARKET])  # catalogue et folder finissant ignorés
    hyper = next(p for p in promos if "Hypermarché" in p.name)
    assert (hyper.valid_from, hyper.valid_to) == (date(2026, 10, 14), date(2026, 10, 26))  # heure belge
    assert hyper.url == f"https://www.myshopi.com/fr/carrefour-folder/{WEEKLY}/0"
    assert hyper.store == "carrefour"
