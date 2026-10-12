from datetime import date
from pathlib import Path

import pytest

from promo_notifier.discount import estimate_discount
from promo_notifier.filtering import filter_promos, normalize
from promo_notifier.mailer import build_html, build_subject, build_text, split_highlights
from promo_notifier.models import Promo
from promo_notifier.page import build_page
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


def test_estimate_discount() -> None:
    cases = {
        "1+1 gratis": 50,
        "3+1 gratis": 25,
        "2+2 GRATIS AU CHOIX": 50,
        "6+6 GRATIS IN PACK": 50,
        "1,5kg+1,5kg GRATIS": 50,
        "2ème à -50%": 25,
        "2e à -50% AU CHOIX": 25,
        "2ème à -70%": 35,
        "-25% pour 3": 25,
        "Jusqu'à -30%": 30,
        "5=livraison gratuite": None,
    }
    for mechanic, expected in cases.items():
        assert estimate_discount(promo("x", mechanic=mechanic)) == expected, mechanic
    # "3 pour €5,5" avec un prix habituel de 2,50 € -> 1 - 5,5/7,5
    assert estimate_discount(promo("x", mechanic="3 pour €5.5", regular_price=2.5)) == 27
    # Les prix, quand ils sont connus, priment sur la mécanique.
    assert estimate_discount(promo("x", mechanic="2 POUR 1,80€", regular_price=2.38, promo_price=1.8)) == 24


def _matches() -> list[tuple[Promo, str]]:
    return [
        (promo("Café <moulu>", mechanic="-25%", regular_price=4.0, promo_price=3.0, url="https://x", discount=25), "café"),
        (promo("Baguette", store="intermarche", pid="2", mechanic="1+1 GRATIS", discount=50), "pain"),
    ]


def test_split_highlights() -> None:
    top, rest = split_highlights(_matches(), 40)
    assert [p.name for p, _ in top] == ["Baguette"]
    assert [p.name for p, _ in rest] == ["Café <moulu>"]


def test_mail_rendering() -> None:
    matches = _matches()
    assert build_subject(matches, 40) == "🛒 2 nouvelles promos dont 1 à ne pas rater — Delhaize (1), Intermarché (1)"
    assert build_subject(matches, 60) == "🛒 2 nouvelles promos — Delhaize (1), Intermarché (1)"
    html = build_html(matches, ["Colruyt : indisponible"], 40, "https://page")
    assert "À ne pas rater" in html and html.index("Baguette") < html.index("Café")
    assert "Café &lt;moulu&gt;" in html
    assert "<s" in html and "3,00 €" in html and "-25 %" in html
    assert 'href="https://page"' in html
    assert "Colruyt : indisponible" in html
    text = build_text(matches, [], 40)
    assert "À NE PAS RATER" in text and "Baguette" in text


def test_page_embeds_data_safely() -> None:
    matches = _matches()
    promos = [p for p, _ in matches] + [promo("Lessive </script>", pid="3")]
    html = build_page(
        promos,
        keywords={p.uid: k for p, k in matches},
        new_uids={matches[0][0].uid},
        stores=["intermarche", "delhaize"],
        min_discount=40,
    )
    assert "/*DATA*/" not in html
    assert "</script>\"" not in html and "Lessive <\\/script>" in html
    assert '"is_new":true' in html and '"keyword":"café"' in html


def test_smtp_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from promo_notifier.mailer import SmtpSettings

    monkeypatch.setenv("SMTP_USER", " moi@gmail.com\n")
    monkeypatch.setenv("SMTP_PASSWORD", "abcd efgh ijkl mnop")
    monkeypatch.delenv("MAIL_TO", raising=False)
    settings = SmtpSettings.from_env()
    assert (settings.user, settings.password, settings.recipient) == ("moi@gmail.com", "abcdefghijklmnop", "moi@gmail.com")

    monkeypatch.setenv("SMTP_USER", "sk-ant-pas-une-adresse")
    with pytest.raises(ValueError, match="SMTP_USER"):
        SmtpSettings.from_env()
