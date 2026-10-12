from promo_notifier.sources.aldi import AldiSource
from promo_notifier.sources.base import Source
from promo_notifier.sources.colruyt import ColruytSource
from promo_notifier.sources.delhaize import DelhaizeSource
from promo_notifier.sources.intermarche import IntermarcheSource
from promo_notifier.sources.lidl import LidlSource

SOURCES: dict[str, Source] = {
    s.name: s for s in (IntermarcheSource(), DelhaizeSource(), ColruytSource(), AldiSource(), LidlSource())
}
