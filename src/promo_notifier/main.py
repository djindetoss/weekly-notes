"""Point d'entrée : récupère, filtre, dédoublonne et envoie le récapitulatif."""

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from promo_notifier.config import load_config
from promo_notifier.discount import estimate_discount
from promo_notifier.filtering import filter_promos
from promo_notifier.mailer import SmtpSettings, build_html, build_subject, build_text, send_mail
from promo_notifier.models import STORE_LABELS, Promo
from promo_notifier.page import build_page, write_page
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


def run(config_path: Path, state_path: Path, site_dir: Path, dry_run: bool, ignore_state: bool) -> int:
    config = load_config(config_path)
    enabled = [name for name, on in config.stores.items() if on]
    unknown = [name for name in enabled if name not in SOURCES]
    if unknown:
        raise SystemExit(f"Enseigne(s) inconnue(s) dans la config : {', '.join(unknown)}")

    promos, warnings = collect(enabled)
    for promo in promos:
        promo.discount = estimate_discount(promo)
    matches = filter_promos(promos, config.keywords, config.exclude)
    seen = SeenStore(state_path)
    new = [(p, k) for p, k in matches if ignore_state or p.uid not in seen]
    log.info("%d promos récupérées, %d correspondent, %d nouvelles", len(promos), len(matches), len(new))

    page = build_page(
        promos,
        keywords={p.uid: k for p, k in matches},
        new_uids={p.uid for p, _ in new},
        stores=enabled,
        min_discount=config.highlight_min_discount,
    )
    write_page(site_dir / "index.html", page)
    log.info("Page écrite : %s", site_dir / "index.html")

    if new:
        threshold, url = config.highlight_min_discount, config.page_url
        subject = build_subject(new, threshold)
        text = build_text(new, warnings, threshold, url)
        if dry_run:
            print(subject, text, sep="\n\n")
        else:
            send_mail(SmtpSettings.from_env(), subject, text, build_html(new, warnings, threshold, url))
            log.info("E-mail envoyé : %s", subject)

    if not dry_run:
        today = date.today()
        seen.add([p.uid for p, _ in new], today)
        seen.save(today)

    # Code de sortie non nul si une source a échoué : GitHub Actions le signale.
    return 1 if warnings else 0


def send_test_mail(config_path: Path) -> int:
    """Mail court pour vérifier l'envoi vers tous les destinataires, sans collecter les promos."""
    config = load_config(config_path)
    settings = SmtpSettings.from_env()
    link = f"Page des promos : {config.page_url}" if config.page_url else ""
    text = f"Test d'envoi : si vous lisez ce message, les notifications de promos vous parviendront.\n{link}\n"
    html = "<p>Test d'envoi : si vous lisez ce message, les notifications de promos vous parviendront.</p>"
    if config.page_url:
        html += f'<p><a href="{config.page_url}">Voir la page des promos →</a></p>'
    send_mail(settings, "🛒 Test d'envoi — promos de la semaine", text, html)
    log.info("Mail de test envoyé à %d destinataire(s)", 1 + len(settings.bcc))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Notifie les nouvelles promos des supermarchés.")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--state", type=Path, default=Path("state/seen.json"))
    parser.add_argument("--site", type=Path, default=Path("site"), help="dossier de la page web générée")
    parser.add_argument("--dry-run", action="store_true", help="affiche le récap sans envoyer ni mémoriser")
    parser.add_argument("--all", action="store_true", help="ignore l'historique (toutes les promos filtrées)")
    parser.add_argument("--test-mail", action="store_true", help="envoie seulement un mail de test")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.test_mail:
        sys.exit(send_test_mail(args.config))
    sys.exit(run(args.config, args.state, args.site, args.dry_run, args.all))


if __name__ == "__main__":
    main()
