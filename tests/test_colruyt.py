import json
from datetime import date
from pathlib import Path

import pytest

from promo_notifier.sources.base import SourceUnavailable
from promo_notifier.sources.colruyt import ColruytSource, ExtractedPromo, find_latest_doc, to_promo

OLD = "colruyt_meilleurs_prix_-_d_pliant_d_251b27c98fdcf3"
NEW = "colruyt_meilleurs_prix_-_d_pliant_d_c20be8284ea37b"


class FakeResponse:
    def __init__(self, text: str = "", status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code
        self.content = text.encode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    """Profil Issuu avec deux dépliants (et un document d'une autre enseigne)."""

    def get(self, url: str, **_: object) -> FakeResponse:
        if url.endswith("/colruytgroup"):
            return FakeResponse(
                f'<a href="/colruytgroup/docs/{OLD}">'
                f'<a href="/colruytgroup/docs/{NEW}">'
                '<a href="/colruytgroup/docs/bioplanet_folder_21_2026">'
            )
        if url.endswith(OLD):
            return FakeResponse('<img src="https://image.isu.pub/260918134412-aaaa/jpg/page_1.jpg">')
        if url.endswith(NEW):
            return FakeResponse('<img src="https://image.isu.pub/261009111853-bbbb/jpg/page_1.jpg">')
        return FakeResponse(status_code=404)


def test_find_latest_doc_picks_newest_revision() -> None:
    assert find_latest_doc(FakeSession()) == (NEW, "261009111853-bbbb")  # type: ignore[arg-type]


def test_to_promo() -> None:
    item = ExtractedPromo(
        brand="Boni Selection",
        name="épinards",
        description="400 g · Origine : France/Pays-Bas/Espagne",
        mechanic="-26%",
        regular_price=1.76,
        promo_price=1.29,
        unit="3,23/kg",
        valid_from="2026-10-14",
        valid_to="2026-10-20",
    )
    promo = to_promo(item, NEW, 2)
    assert promo.store == "colruyt"
    assert promo.valid_from == date(2026, 10, 14) and promo.valid_to == date(2026, 10, 20)
    assert promo.url == f"https://issuu.com/colruytgroup/docs/{NEW}/2"
    assert promo.product_id == to_promo(item, NEW, 5).product_id  # stable d'une page à l'autre
    bad_date = item.model_copy(update={"valid_to": "20/10"})
    assert to_promo(bad_date, NEW, 2).valid_to is None


def test_fetch_uses_cache_without_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    cached = to_promo(ExtractedPromo(brand=None, name="carottes", description=None, mechanic="1+1 gratis",
                                     regular_price=2.68, promo_price=None, unit=None,
                                     valid_from=None, valid_to=None), NEW, 2)
    cache = tmp_path / "colruyt_cache.json"
    cache.write_text(json.dumps({"doc": NEW, "revision": "261009111853-bbbb",
                                 "promos": [cached.model_dump(mode="json")]}))
    promos = ColruytSource(cache).fetch(FakeSession())  # type: ignore[arg-type]
    assert [p.name for p in promos] == ["carottes"]

    # Nouveau dépliant, pas de clé API : erreur explicite plutôt qu'un appel.
    cache.write_text(json.dumps({"doc": OLD, "revision": "260918134412-aaaa", "promos": []}))
    with pytest.raises(SourceUnavailable, match="ANTHROPIC_API_KEY"):
        ColruytSource(cache).fetch(FakeSession())  # type: ignore[arg-type]
