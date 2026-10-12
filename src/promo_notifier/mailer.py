"""Construction et envoi du récapitulatif par e-mail (smtplib).

L'objet du mail sert d'alerte courte (visible dans la notification du
téléphone), le corps HTML contient le récapitulatif complet.
"""

import os
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
        user = os.environ["SMTP_USER"]
        return cls(
            host=os.environ.get("SMTP_HOST", "smtp.gmail.com"),
            port=int(os.environ.get("SMTP_PORT", "465")),
            user=user,
            password=os.environ["SMTP_PASSWORD"],
            recipient=os.environ.get("MAIL_TO") or user,
        )


def _by_store(matches: list[tuple[Promo, str]]) -> dict[str, list[tuple[Promo, str]]]:
    grouped: dict[str, list[tuple[Promo, str]]] = defaultdict(list)
    for promo, keyword in matches:
        grouped[promo.store].append((promo, keyword))
    for items in grouped.values():
        items.sort(key=lambda item: (item[1].casefold(), item[0].name.casefold()))
    return dict(grouped)


def build_subject(matches: list[tuple[Promo, str]]) -> str:
    grouped = _by_store(matches)
    detail = ", ".join(f"{STORE_LABELS[s]} ({len(items)})" for s, items in grouped.items())
    plural = "s" if len(matches) > 1 else ""
    return f"🛒 {len(matches)} nouvelle{plural} promo{plural} — {detail}"


def _price(value: float | None) -> str:
    return f"{value:.2f} €".replace(".", ",") if value is not None else ""


def _period(promo: Promo) -> str:
    if promo.valid_from and promo.valid_to:
        return f"{promo.valid_from:%d/%m} → {promo.valid_to:%d/%m}"
    if promo.valid_to:
        return f"jusqu'au {promo.valid_to:%d/%m}"
    return ""


def build_html(matches: list[tuple[Promo, str]], warnings: list[str]) -> str:
    th = 'style="text-align:left;padding:6px;border-bottom:2px solid #ddd"'
    td = 'style="padding:6px;border-bottom:1px solid #eee;vertical-align:top"'
    parts = ['<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;font-size:14px;color:#222">']
    for store, items in _by_store(matches).items():
        parts.append(f'<h2 style="font-size:18px;margin:20px 0 8px">{escape(STORE_LABELS[store])}</h2>')
        parts.append('<table style="border-collapse:collapse;width:100%">')
        parts.append(
            f"<tr><th {th}>Produit</th><th {th}>Promo</th><th {th}>Prix</th>"
            f"<th {th}>Période</th><th {th}>Mot-clé</th></tr>"
        )
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
            parts.append(
                f"<tr><td {td}><b>{name}</b><br><span style=\"color:#666\">{details}</span></td>"
                f'<td {td}><b style="color:#c00">{escape(promo.mechanic or "")}</b></td>'
                f"<td {td}>{price}</td><td {td}>{_period(promo)}</td>"
                f"<td {td}>{escape(keyword)}</td></tr>"
            )
        parts.append("</table>")
    if warnings:
        parts.append('<p style="color:#a60;margin-top:24px"><b>Sources en erreur :</b><br>')
        parts.append("<br>".join(escape(w) for w in warnings))
        parts.append("</p>")
    parts.append("</div>")
    return "\n".join(parts)


def build_text(matches: list[tuple[Promo, str]], warnings: list[str]) -> str:
    lines = []
    for store, items in _by_store(matches).items():
        lines.append(f"\n== {STORE_LABELS[store]} ==")
        for promo, keyword in items:
            price = _price(promo.promo_price) or _price(promo.regular_price)
            lines.append(f"- {promo.name} [{promo.mechanic or ''}] {price} {_period(promo)} ({keyword})")
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
