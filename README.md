# weekly-notes

Récupère les promos de la semaine (Intermarché, Delhaize, Colruyt, Aldi, Lidl, Carrefour), garde celles qui
correspondent à mes mots-clés et m'envoie **un e-mail** avec uniquement les
promos **nouvelles** depuis le dernier passage. Usage strictement personnel.

L'objet du mail sert d'alerte courte (`🛒 7 nouvelles promos dont 2 à ne pas
rater — Delhaize (4), Intermarché (3)`). Le corps commence par **⭐ À ne pas
rater** : les promos dont la réduction estimée atteint `highlight_min_discount`
(40 % par défaut), triées de la plus forte à la plus faible ; viennent ensuite
les autres promos, par enseigne.

La réduction est estimée à partir des prix (habituel / promo) quand ils sont
connus, sinon de la mécanique : 1+1 gratis = 50 %, 3+1 gratis = 25 %,
2e à -50 % = 25 %, « 3 pour 5 € » avec le prix unitaire… (`discount.py`).

**Page filtrable** : chaque exécution génère aussi `site/index.html`, publiée
sur GitHub Pages, avec **toutes** les promos de la semaine (pas seulement mes
mots-clés) : recherche, enseignes, réduction minimale, « mes mots-clés »,
« nouvelles », tri par réduction ou date de fin. Renseigner son adresse dans
`page_url` (config.yaml) pour qu'elle soit liée depuis le mail.

## Sources

| Enseigne | Méthode | Remarques |
|---|---|---|
| Intermarché | HTML statique de `/produits/?_pagination=N` | ~16 pages, quelques secondes. Les produits du folder sans réduction sont ignorés. |
| Delhaize | API GraphQL interne `api/v1/?operationName=ProductList` | ~1 500 promos, 31 pages de 50, ~5 min (l'API est lente). Si Delhaize change son front, mettre à jour `QUERY_HASH` dans `sources/delhaize.py`. |
| Colruyt | Dépliant publié par Colruyt sur Issuu (`issuu.com/colruytgroup`), pages lues par Claude Haiku 5.5 (`leaflet.py`) | Le site colruyt.be est protégé par un anti-bot : pas de contournement. Le dépliant (~37 pages, toutes les 2 semaines) n'est analysé qu'une fois, résultat en cache dans `state/colruyt_cache.json`. Coût : quelques centimes par dépliant. Lecture par IA : vérifier un prix en cas de doute (lien vers la page du dépliant). |
| Aldi | JSON intégré à `/fr/offres.html` | ~100 promos (semaine en cours et suivante), prix barré, mécanique et dates. Les articles sans réduction (simples nouveautés) sont ignorés. |
| Lidl | Dépliant publié par Lidl (`folder-fr.lidl.be`, API publique de la visionneuse), pages lues par Claude Haiku 5.5 | Dépliant hebdomadaire (~36 pages) ; celui de la semaine suivante est traité dès sa publication. Cache dans `state/lidl_cache.json`. |
| Carrefour | Folders Hypermarché et Market republiés par myShopi (`myshopi.com`, robots autorisés), pages lues par Claude Haiku 5.5 | carrefour.be est protégé par Cloudflare : pas de contournement. Hypermarché : un folder de 2 semaines publié chaque semaine (~50 pages) ; Market : un folder par semaine (~25 pages) ; catalogues thématiques ignorés. Cache dans `state/carrefour_cache.json`. Dépend de myShopi : si leur site change, la source tombe (signalé dans le mail). |

## Configuration

`config.yaml` : mots-clés (`keywords`), exclusions (`exclude`) et enseignes
actives (`stores`). Correspondance insensible à la casse et aux accents, au
début d'un mot.

Secrets GitHub (Settings → Secrets and variables → Actions) :

| Secret | Valeur |
|---|---|
| `SMTP_USER` | adresse Gmail d'envoi |
| `SMTP_PASSWORD` | [mot de passe d'application Gmail](https://myaccount.google.com/apppasswords) |
| `MAIL_TO` | destinataires supplémentaires, séparés par des virgules (optionnel ; en copie cachée, le mail part toujours aussi à `SMTP_USER`) |
| `ANTHROPIC_API_KEY` | clé API Anthropic pour lire le dépliant Colruyt ([console](https://console.anthropic.com/settings/keys)) |

Autre fournisseur SMTP : variables `SMTP_HOST` / `SMTP_PORT` (465 = SSL, sinon STARTTLS).

## Exécution

GitHub Actions (`.github/workflows/run.yml`) : mardi et jeudi à 06:00 UTC
(nouveaux folders Intermarché et Delhaize), plus lancement manuel avec option
*dry run*. Les promos notifiées sont mémorisées dans `state/seen.json` (et les
dépliants Colruyt / Lidl / Carrefour analysés dans `state/*_cache.json`), commités
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
