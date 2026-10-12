import json
from datetime import date
from pathlib import Path

from promo_notifier.sources.base import parse_price
from promo_notifier.sources.delhaize import parse_products
from promo_notifier.sources.intermarche import parse_page, parse_validity

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_price() -> None:
    assert parse_price("€7,49") == 7.49
    assert parse_price("79,99") == 79.99
    assert parse_price("1.234,50 €") == 1234.5
    assert parse_price(None) is None
    assert parse_price("—") is None


def test_intermarche_validity() -> None:
    assert parse_validity("Valide du 13/10 au 18/10/2026") == (date(2026, 10, 13), date(2026, 10, 18))
    assert parse_validity("Valide du 29/12 au 03/01/2027") == (date(2026, 12, 29), date(2027, 1, 3))
    assert parse_validity("rien") == (None, None)


def test_intermarche_page() -> None:
    promos = parse_page((FIXTURES / "intermarche_page1.html").read_text(encoding="utf-8"))
    assert len(promos) == 4  # 8 produits du folder sans réduction écartés
    assert all(p.mechanic or p.regular_price for p in promos)
    valise = next(p for p in promos if p.product_id == "3700245483756")
    assert valise.name == "Aérial"
    assert valise.description is not None and valise.description.startswith("Lot de valise cabine")
    assert valise.mechanic == "-50%"
    assert valise.regular_price == 79.99
    assert valise.promo_price == 39.99
    assert valise.unit == "La pièce"
    assert valise.valid_to == date(2026, 10, 18)
    apta = next(p for p in promos if p.product_id == "41547151")
    assert apta.mechanic == "2+2 GRATIS AU CHOIX"
    assert apta.promo_price is None


def test_delhaize_products() -> None:
    payload = json.loads((FIXTURES / "delhaize_page0.json").read_text(encoding="utf-8"))
    promos = parse_products(payload)
    assert len(promos) == 8
    creatine = next(p for p in promos if "Creatine" in p.name)
    assert creatine.brand == "Optimum Nutrition"
    assert creatine.mechanic == "-25%"
    assert creatine.regular_price == 20.99
    assert creatine.promo_price == 15.74
    assert creatine.valid_from == date(2026, 10, 8)
    assert creatine.valid_to == date(2026, 10, 14)
    assert creatine.url and creatine.url.startswith("https://www.delhaize.be/fr/shop/")
    gratis = next(p for p in promos if p.mechanic == "1+1 gratis")
    assert gratis.promo_price is None
