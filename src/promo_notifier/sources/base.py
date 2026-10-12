from typing import Protocol

import requests

from promo_notifier.models import Promo

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 30
# Pause entre deux pages pour rester poli avec les sites.
PAGE_DELAY_SECONDS = 0.5


class SourceUnavailable(Exception):
    """La source ne peut pas être interrogée automatiquement."""


class Source(Protocol):
    name: str

    def fetch(self, session: requests.Session) -> list[Promo]: ...


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "fr-BE,fr;q=0.9"})
    return session


def parse_price(text: str | None) -> float | None:
    """'€7,49' / '79,99' / '1.234,50 €' -> float."""
    if not text:
        return None
    cleaned = "".join(c for c in text if c.isdigit() or c in ",.")
    if not cleaned:
        return None
    cleaned = cleaned.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None
