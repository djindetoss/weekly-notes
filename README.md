# promo-notifier

Récupère les promos de la semaine (Intermarché, Delhaize), garde celles qui
correspondent à mes mots-clés et m'envoie **un e-mail** avec uniquement les
promos **nouvelles** depuis le dernier passage. Usage strictement personnel.

L'objet du mail sert d'alerte courte (`🛒 7 nouvelles promos — Delhaize (4),
Intermarché (3)`) ; le corps contient le récapitulatif complet par enseigne.

## Sources

| Enseigne | Méthode | Remarques |
|---|---|---|
| Intermarché | HTML statique de `/produits/?_pagination=N` | ~16 pages, quelques secondes. Les produits du folder sans réduction sont ignorés. |
| Delhaize | API GraphQL interne `api/v1/?operationName=ProductList` | ~1 500 promos, 31 pages de 50, ~5 min (l'API est lente). Si Delhaize change son front, mettre à jour `QUERY_HASH` dans `sources/delhaize.py`. |
| Colruyt | — | Désactivé : les produits viennent d'une API à clé applicative et le site renvoie une page anti-bot. Pas de contournement. |

## Configuration

`config.yaml` : mots-clés (`keywords`), exclusions (`exclude`) et enseignes
actives (`stores`). Correspondance insensible à la casse et aux accents, au
début d'un mot.

Secrets GitHub (Settings → Secrets and variables → Actions) :

| Secret | Valeur |
|---|---|
| `SMTP_USER` | adresse Gmail d'envoi |
| `SMTP_PASSWORD` | [mot de passe d'application Gmail](https://myaccount.google.com/apppasswords) |
| `MAIL_TO` | destinataire (optionnel, défaut : `SMTP_USER`) |

Autre fournisseur SMTP : variables `SMTP_HOST` / `SMTP_PORT` (465 = SSL, sinon STARTTLS).

## Exécution

GitHub Actions (`.github/workflows/run.yml`) : mardi et jeudi à 06:00 UTC
(nouveaux folders Intermarché et Delhaize), plus lancement manuel avec option
*dry run*. Les promos notifiées sont mémorisées dans `state/seen.json`, commité
par le workflow (entrées oubliées après 60 jours). Si une source échoue, les
autres sont quand même traitées, l'erreur figure dans le mail et le run est
marqué en échec.

En local :

```bash
python3.12 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/promo-notifier --dry-run      # affiche sans envoyer ni mémoriser
.venv/bin/promo-notifier --dry-run --all  # ignore l'historique
.venv/bin/pytest -q
```

Le premier envoi contient toutes les promos correspondantes en cours ; les
suivants, seulement les nouvelles.
