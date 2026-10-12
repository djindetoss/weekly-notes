"""Colruyt : non automatisable proprement à ce jour.

Constat (octobre 2026) :
- les pages /fr/actions/* sont servies, mais les produits sont chargés par
  apip.colruyt.be/.../user-promotions/by-date-range, qui exige une clé
  applicative (401 "Unauthorized application request") ;
- les autres pages (dépliants, etc.) renvoient 405 ou une page "AntiBot".

Le module est volontairement désactivé (config.yaml : stores.colruyt: false)
plutôt que de contourner la protection anti-bot. À revoir si Colruyt publie
un flux ou un dépliant accessible (PDF, Publitas…).
"""

import requests

from promo_notifier.models import Promo
from promo_notifier.sources.base import SourceUnavailable


class ColruytSource:
    name = "colruyt"

    def fetch(self, session: requests.Session) -> list[Promo]:
        raise SourceUnavailable("Colruyt protège ses promos par un anti-bot ; source désactivée.")
