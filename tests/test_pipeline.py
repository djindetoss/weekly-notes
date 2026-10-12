from datetime import date
from pathlib import Path

from promo_notifier.filtering import filter_promos, normalize
from promo_notifier.mailer import build_html, build_subject, build_text
from promo_notifier.models import Promo
from promo_notifier.state import SeenStore


def promo(name: str, store: str = "delhaize", pid: str = "1", **kw: object) -> Promo:
    return Promo(store=store, product_id=pid, name=name, **kw)  # type: ignore[arg-type]


def test_normalize() -> None:
    assert normalize("Café CRÈME") == "cafe creme"


def test_filter_keywords_and_exclude() -> None:
    promos = [
        promo("Café moulu", pid="1"),
        promo("Laitue iceberg", pid="2"),
        promo("Lait demi-écrémé", pid="3"),
        promo("Pistolets", pid="4"),
        promo("Chocolat au lait", pid="5"),
    ]
    matches = filter_promos(promos, ["cafe", "lait"], ["laitue"])
    assert [(p.product_id, k) for p, k in matches] == [("1", "cafe"), ("3", "lait"), ("5", "lait")]


def test_uid_changes_with_period() -> None:
    a = promo("Café", mechanic="1+1", valid_to=date(2026, 10, 14))
    b = promo("Café", mechanic="1+1", valid_to=date(2026, 10, 21))
    assert a.uid != b.uid


def test_seen_store_roundtrip_and_retention(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    store = SeenStore(path)
    store.add(["old"], date(2026, 1, 1))
    store.add(["recent"], date(2026, 10, 1))
    store.save(date(2026, 10, 12))
    reloaded = SeenStore(path)
    assert "recent" in reloaded
    assert "old" not in reloaded


def test_mail_rendering() -> None:
    matches = [
        (promo("Café <moulu>", mechanic="-25%", regular_price=4.0, promo_price=3.0, url="https://x"), "café"),
        (promo("Baguette", store="intermarche", pid="2", mechanic="2 POUR 1,80€"), "pain"),
    ]
    assert build_subject(matches) == "🛒 2 nouvelles promos — Delhaize (1), Intermarché (1)"
    html = build_html(matches, ["Colruyt : indisponible"])
    assert "Café &lt;moulu&gt;" in html
    assert "<s" in html and "3,00 €" in html
    assert "Colruyt : indisponible" in html
    assert "Baguette" in build_text(matches, [])
