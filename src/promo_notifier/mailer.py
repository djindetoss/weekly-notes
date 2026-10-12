"""Construction et envoi du récapitulatif par e-mail (smtplib).

L'objet du mail sert d'alerte courte (visible dans la notification du
téléphone), le corps HTML contient le récapitulatif complet.
"""

import os
import re
import smtplib
from collections import defaultdict
from dataclasses import dataclass
from email.message import EmailMessage
from html import escape

from promo_notifier.models import STORE_LABELS, Promo


@dataclass(frozen=True)
class SmtpSettings:
    host: str
    port: int
    user: str
    password: str
    recipient: str

    @classmethod
    def from_env(cls) -> "SmtpSettings":
        user = os.environ.get("SMTP_USER", "").strip()
        # Google affiche les mots de passe d'application par groupes de 4 : "abcd efgh ijkl mnop".
        password = "".join(os.environ.get("SMTP_PASSWORD", "").split())
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", user):
            raise ValueError(
                f"SMTP_USER doit être l'adresse e-mail d'envoi (valeur reçue : {len(user)} caractères, sans format d'adresse)"
            )
        if not password:
            raise ValueError("SMTP_PASSWORD est vide")
        recipient = os.environ.get("MAIL_TO", "").strip() or user
        return cls(
            host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            port=int(os.environ.get("SMTP_PORT", "465")),
            user=user,
            password=password,
            recipient=recipient,
        )


Match = tuple[Promo, str]


def split_highlights(matches: list[Match], min_discount: int) -> tuple[list[Match], list[Match]]:
    """Sépare les promos "à ne pas rater" (réduction >= seuil) des autres."""
    top = [m for m in matches if (m[0].discount or 0) >= min_discount]
    top.sort(key=lambda m: (-(m[0].discount or 0), m[0].name.casefold()))
    rest = [m for m in matches if (m[0].discount or 0) < min_discount]
    return top, rest


def _by_store(matches: list[Match]) -> dict[str, list[Match]]:
    grouped: dict[str, list[Match]] = defaultdict(list)
    for promo, keyword in matches:
        grouped[promo.store].append((promo, keyword))
    for items in grouped.values():
        items.sort(key=lambda item: (item[1].casefold(), item[0].name.casefold()))
    return dict(grouped)


def build_subject(matches: list[Match], min_discount: int) -> str:
    top, _ = split_highlights(matches, min_discount)
    detail = ", ".join(f"{STORE_LABELS[s]} ({len(items)})" for s, items in _by_store(matches).items())
    plural = "s" if len(matches) > 1 else ""
    highlight = f" dont {len(top)} à ne pas rater" if top else ""
    return f"🛒 {len(matches)} nouvelle{plural} promo{plural}{highlight} — {detail}"


def _price(value: float | None) -> str:
    return f"{value:.2f} €".replace(".", ",") if value is not None else ""


def _discount(promo: Promo) -> str:
    return f"-{promo.discount} %" if promo.discount else ""


def _period(promo: Promo) -> str:
    if promo.valid_from and promo.valid_to:
        return f"{promo.valid_from:%d/%m} → {promo.valid_to:%d/%m}"
    if promo.valid_to:
        return f"jusqu'au {promo.valid_to:%d/%m}"
    return ""


_TH = 'style="text-align:left;padding:6px;border-bottom:2px solid #ddd"'
_TD = 'style="padding:6px;border-bottom:1px solid #eee;vertical-align:top"'


def _html_table(items: list[Match], show_store: bool) -> list[str]:
    store_th = f"<th {_TH}>Enseigne</th>" if show_store else ""
    rows = [
        '<table style="border-collapse:collapse;width:100%">',
        f"<tr>{store_th}<th {_TH}>Produit</th><th {_TH}>Promo</th><th {_TH}>Réduction</th>"
        f"<th {_TH}>Prix</th><th {_TH}>Période</th><th {_TH}>Mot-clé</th></tr>",
    ]
    for promo, keyword in items:
        name = escape(promo.name)
        if promo.url:
            name = f'<a href="{escape(promo.url)}" style="color:#0a58ca">{name}</a>'
        details = " · ".join(escape(x) for x in (promo.brand, promo.description) if x)
        regular = _price(promo.regular_price)
        promo_price = _price(promo.promo_price)
        if promo_price and regular:
            price = f'<s style="color:#888">{regular}</s> <b>{promo_price}</b>'
        else:
            price = f"<b>{promo_price}</b>" if promo_price else regular
        if promo.unit:
            price += f'<br><span style="color:#888">{escape(promo.unit)}</span>'
        store_td = f"<td {_TD}>{escape(STORE_LABELS[promo.store])}</td>" if show_store else ""
        rows.append(
            f"<tr>{store_td}<td {_TD}><b>{name}</b><br><span style=\"color:#666\">{details}</span></td>"
            f'<td {_TD}><b style="color:#c00">{escape(promo.mechanic or "")}</b></td>'
            f"<td {_TD}><b>{_discount(promo)}</b></td>"
            f"<td {_TD}>{price}</td><td {_TD}>{_period(promo)}</td>"
            f"<td {_TD}>{escape(keyword)}</td></tr>"
        )
    rows.append("</table>")
    return rows


def build_html(matches: list[Match], warnings: list[str], min_discount: int, page_url: str | None = None) -> str:
    top, rest = split_highlights(matches, min_discount)
    parts = ['<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:14px;color:#222">']
    if page_url:
        parts.append(
            f'<p><a href="{escape(page_url)}" style="color:#0a58ca">Voir toutes les promos de la semaine '
            "avec filtres →</a></p>"
        )
    if top:
        parts.append(
            '<h2 style="font-size:20px;margin:20px 0 8px;color:#c00">'
            f"⭐ À ne pas rater (réduction ≥ {min_discount} %)</h2>"
        )
        parts.extend(_html_table(top, show_store=True))
    if rest:
        if top:
            parts.append('<h2 style="font-size:18px;margin:28px 0 0;color:#555">Autres promos</h2>')
        for store, items in _by_store(rest).items():
            parts.append(f'<h3 style="font-size:16px;margin:16px 0 8px">{escape(STORE_LABELS[store])}</h3>')
            parts.extend(_html_table(items, show_store=False))
    if warnings:
        parts.append('<p style="color:#a60;margin-top:24px"><b>Sources en erreur :</b><br>')
        parts.append("<br>".join(escape(w) for w in warnings))
        parts.append("</p>")
    parts.append("</div>")
    return "\n".join(parts)


def _text_line(promo: Promo, keyword: str, with_store: bool = False) -> str:
    price = _price(promo.promo_price) or _price(promo.regular_price)
    store = f"{STORE_LABELS[promo.store]} — " if with_store else ""
    discount = f" {_discount(promo)}" if promo.discount else ""
    return f"- {store}{promo.name} [{promo.mechanic or ''}]{discount} {price} {_period(promo)} ({keyword})"


def build_text(matches: list[Match], warnings: list[str], min_discount: int, page_url: str | None = None) -> str:
    top, rest = split_highlights(matches, min_discount)
    lines = [f"Toutes les promos avec filtres : {page_url}"] if page_url else []
    if top:
        lines.append(f"\n== À NE PAS RATER (réduction ≥ {min_discount} %) ==")
        lines.extend(_text_line(p, k, with_store=True) for p, k in top)
    for store, items in _by_store(rest).items():
        lines.append(f"\n== {STORE_LABELS[store]} ==")
        for promo, keyword in items:
            lines.append(_text_line(promo, keyword))
            if promo.description:
                lines.append(f"    {promo.description}")
    if warnings:
        lines.append("\nSources en erreur :")
        lines.extend(f"- {w}" for w in warnings)
    return "\n".join(lines).strip() + "\n"


def send_mail(settings: SmtpSettings, subject: str, text: str, html: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"Promo Notifier <{settings.user}>"
    msg["To"] = settings.recipient
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    if settings.port == 465:
        with smtplib.SMTP_SSL(settings.host, settings.port, timeout=30) as smtp:
            smtp.login(settings.user, settings.password)
            smtp.send_message(msg)
    else:
        with smtplib.SMTP(settings.host, settings.port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(settings.user, settings.password)
            smtp.send_message(msg)
