from datetime import date
from pathlib import Path
from typing import Any

import pytest

from promo_notifier.models import Promo
from promo_notifier.sources import lidl
from promo_notifier.sources.leaflet import ExtractedPromo, load_cache, save_cache

CURRENT = "fr-folder-12-10-17-10"
ENDED = "fr-folder-05-10-10-10"


def flyer(identifier: str, start: str, end: str) -> dict[str, Any]:
    return {
        "id": f"id-{identifier}",
        "offerStartDate": start,
        "offerEndDate": end,
        "pages": [{"number": 1, "image": f"https://img/{identifier}/1.jpg"}],
    }


FLYERS = {CURRENT: flyer(CURRENT, "2026-10-12", "2026-10-17"), ENDED: flyer(ENDED, "2026-10-05", "2026-10-10")}


class FakeResponse:
    def __init__(self, text: str = "", payload: Any = None) -> None:
        self.text, self.content, self._payload = text, text.encode(), payload

    status_code = 200

    def raise_for_status(self) -> None:
        pass

    def json(self) -> Any:
        return self._payload


class FakeSession:
    def get(self, url: str, params: dict[str, Any] | None = None, **_: object) -> FakeResponse:
        if url == lidl.LEAFLETS_PAGE:
            return FakeResponse("".join(f'<a href="https://folder-fr.lidl.be/{f}/page/1">' for f in FLYERS))
        if url == lidl.FLYER_API:
            assert params is not None
            return FakeResponse(payload={"success": True, "flyer": FLYERS[params["flyer_identifier"]]})
        return FakeResponse("image")


@pytest.fixture
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeDate(date):
        @classmethod
        def today(cls) -> "FakeDate":
            return cls(2026, 10, 13)

    monkeypatch.setattr(lidl, "date", FakeDate)


def test_lidl_extracts_current_flyer_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, today: None) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    calls: list[int] = []

    def fake_extract(client: object, image: bytes, page: int, store: str) -> list[ExtractedPromo]:
        calls.append(page)
        return [ExtractedPromo(brand="Milbona", name="yaourt grec", description="1 kg", mechanic="-30%",
                               regular_price=2.49, promo_price=1.74, unit=None, valid_from=None, valid_to=None)]

    monkeypatch.setattr(lidl, "extract_page", fake_extract)
    cache = tmp_path / "lidl_cache.json"
    save_cache(cache, {"id-old": [Promo(store="lidl", product_id="x", name="vieux")]})

    promos = lidl.LidlSource(cache).fetch(FakeSession())  # type: ignore[arg-type]
    assert [p.name for p in promos] == ["yaourt grec"]
    assert (promos[0].valid_from, promos[0].valid_to) == (date(2026, 10, 12), date(2026, 10, 17))
    assert promos[0].url == f"https://folder-fr.lidl.be/{CURRENT}/page/1"
    assert calls == [1]  # le dépliant terminé n'est pas analysé
    assert list(load_cache(cache)) == [f"id-{CURRENT}"]  # l'ancien est oublié

    lidl.LidlSource(cache).fetch(FakeSession())  # type: ignore[arg-type]
    assert calls == [1]  # second passage : cache
