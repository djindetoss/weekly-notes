"""Point d'entrée : récupère, filtre, dédoublonne et envoie le récapitulatif."""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from promo_notifier.config import load_config
from promo_notifier.filtering import filter_promos
from promo_notifier.mailer import SmtpSettings, build_html, build_subject, build_text, send_mail
from promo_notifier.models import STORE_LABELS, Promo
from promo_notifier.sources import SOURCES
from promo_notifier.sources.base import make_session
from promo_notifier.state import SeenStore

log = logging.getLogger("promo_notifier")


def collect(store_names: list[str]) -> tuple[list[Promo], list[str]]:
    """Interroge chaque source ; une source en échec n'empêche pas les autres."""
    session = make_session()
    promos: list[Promo] = []
    warnings: list[str] = []
    for name in store_names:
        try:
            promos.extend(SOURCES[name].fetch(session))
        except Exception as exc:  # noqa: BLE001 — on isole chaque source
            log.exception("Échec de la source %s", name)
            warnings.append(f"{STORE_LABELS.get(name, name)} : {exc}")
    return promos, warnings


def run(config_path: Path, state_path: Path, dry_run: bool, ignore_state: bool) -> int:
    config = load_config(config_path)
    enabled = [name for name, on in config.stores.items() if on]
    unknown = [name for name in enabled if name not in SOURCES]
    if unknown:
        raise SystemExit(f"Enseigne(s) inconnue(s) dans la config : {', '.join(unknown)}")

    promos, warnings = collect(enabled)
    matches = filter_promos(promos, config.keywords, config.exclude)
    seen = SeenStore(state_path)
    new = [(p, k) for p, k in matches if ignore_state or p.uid not in seen]
    log.info("%d promos récupérées, %d correspondent, %d nouvelles", len(promos), len(matches), len(new))

    if new:
        subject = build_subject(new)
        text = build_text(new, warnings)
        if dry_run:
            print(subject, text, sep="\n\n")
        else:
            send_mail(SmtpSettings.from_env(), subject, text, build_html(new, warnings))
            log.info("E-mail envoyé : %s", subject)

    if not dry_run:
        today = date.today()
        seen.add([p.uid for p, _ in new], today)
        seen.save(today)

    # Code de sortie non nul si une source a échoué : GitHub Actions le signale.
    return 1 if warnings else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Notifie les nouvelles promos des supermarchés.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--state", type=Path, default=Path("state/seen.json"))
    parser.add_argument("--dry-run", action="store_true", help="affiche le récap sans envoyer ni mémoriser")
    parser.add_argument("--all", action="store_true", help="ignore l'historique (toutes les promos filtrées)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    sys.exit(run(args.config, args.state, args.dry_run, args.all))


if __name__ == "__main__":
    main()
