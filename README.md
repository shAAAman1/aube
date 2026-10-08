# Aube

Veille physique locale : la machine lit la nuit les flux de physique (arXiv, CERN,
INSPIRE-HEP), trie ce qui compte et rédige une synthèse lue au réveil.

**État : phase 1, collecte et archive.** Pas de tri ni de synthèse pour l'instant.

## Principes

- **Local-first.** Seule la récupération des flux passe par le réseau.
- **Rejouable.** Chaque run écrit un manifeste : URL, horodatage et SHA256 de chaque
  réponse brute, commit git, hash du code et de la configuration.
- **Contenu web non fiable.** Le XML est parsé avec `defusedxml`. Rien de ce qui est reçu
  n'est exécuté ni interprété comme une instruction.
- **Référencé (principe fondateur).** Toute donnée remonte, de façon vérifiable, à sa
  source publique et aux octets exacts reçus. Une référence irrésoluble est un défaut.
- **Falsifiable.** Le critère de phase est vérifié par un audit qui peut échouer.

## Architecture de l'archive

```
data/
  blobs/ab/abcd….gz     octets bruts reçus, nommés par leur SHA256 (gzip mtime=0, déterministe)
  manifests/<run>.json  journal complet d'un run : source de vérité
  aube.sqlite           index dérivé, reconstructible à partir des deux précédents
```

| Source | Méthode | Fenêtre | Clé anti-doublon |
|---|---|---|---|
| arXiv | OAI-PMH `arXivRaw`, un set par catégorie, jours de datestamp | dernier succès − 3 j → hier (UTC, jours clos) | id + version |
| arXiv (témoin) | RSS quotidien `rss.arxiv.org` | — | sert uniquement à l'audit |
| CERN | RSS WordPress `home.cern/feed/`, pages 1 et 2 | glissante (20 derniers) | guid + empreinte du contenu |
| INSPIRE | API REST, `da` (= `_created`, date d'entrée dans INSPIRE) | dernier succès − 3 j → hier | control_number + `updated` |

Une nouvelle version d'un preprint (v2) est un **nouvel élément**, pas un doublon. arXivRaw liste
toutes les versions d'un enregistrement : chacune devient un élément, y compris une v2 déjà
dépassée par une v3 au moment du passage.

Jusqu'au 4 octobre 2026, arXiv était collecté par l'API Atom avec un filtre `lastUpdatedDate`.
Ce filtre n'existe pas : l'API le réécrit en silence en `submittedDate`, si bien que les
remplacements d'articles anciens et les annonces tardives manquaient alors que le total annoncé
« collait ». Les blobs de cette période restent archivés et rejoués par l'audit.

## Critère de phase 1 et audit

> Deux semaines de flux archivés sans perte ni doublon.

`python -m aube audit` relit les données primaires et vérifie :

1. **Intégrité.** Chaque blob existe et son SHA256 recalculé correspond au manifeste.
2. **Continuité.** Les fenêtres arXiv et INSPIRE se recouvrent sans trou. Après une panne,
   la fenêtre suivante repart du dernier succès. Pour CERN, chaque lecture doit
   recouper la précédente, sinon des actualités ont pu passer entre deux runs.
3. **Complétude.** INSPIRE : le nombre d'identifiants distincts reçus égale le total annoncé,
   stable pendant la pagination. arXiv (OAI-PMH) : aucun total n'est fourni ; on suit les
   `resumptionToken` jusqu'à leur absence, et le témoin RSS sert de contrôle externe.
4. **Témoin indépendant.** Toute annonce du RSS quotidien d'arXiv vieille de plus de
   24 h doit se trouver dans l'archive API. C'est le seul contrôle externe de la perte.
5. **Rejouabilité.** Le rejeu des parseurs sur les blobs reproduit exactement l'index.
6. **Références.** Chaque élément indexé pointe vers un blob qui le contient réellement
   (re-parsing). `python -m aube ref arxiv:<id>v<n>` montre la chaîne complète :
   source publique → blob SHA256 → manifeste (URL, date, commit).
7. **Doublons sémantiques.** Aucun même objet sous deux clés.
8. **Erreurs de run.** Toute erreur d'un run des 14 derniers jours bloque le critère.

Les problèmes datés (erreur de run, trou CERN possible, annonce du témoin absente de
l'archive) ne bloquent que s'ils tombent dans les 14 derniers jours. Les plus anciens sont
affichés comme non bloquants (`hors_fenetre`), puisque les manifestes ne sont jamais supprimés.
Les contrôles qui décrivent l'état actuel de l'archive (intégrité, rejeu, doublons, trous de
fenêtre, retard, témoin inactif) bloquent toujours.

Le critère est **ATTEINT** quand on a 14 jours consécutifs de runs sans erreur et aucun
problème détecté. Code de sortie : 0 si atteint, 2 sinon.

### Limites connues (à ne pas oublier)

- Le témoin RSS ne couvre que les annonces quotidiennes. Il est reconstruit vers 04:00 UTC
  et le timer passe à 00:40 UTC : chaque run lit le flux de la veille, et un run manqué ou
  rattrapé après 04:00 UTC fait perdre une journée de témoin sans que l'audit le signale.
- Le format d'un flux RSS rempli (guid versionné, `announce_type`) n'est que documenté :
  à confirmer sur un vrai blob un jour ouvré.
- CERN : le contrôle de recoupement signale une perte *possible*, pas certaine.

## Installation (Debian, Bixeon)

```bash
cd ~/aube
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
cp config.local.toml.example config.local.toml   # mets ton contact dans user_agent
.venv/bin/python -m aube collect                 # premier run manuel
.venv/bin/python -m aube audit

# collecte nocturne (timer systemd utilisateur)
mkdir -p ~/.config/systemd/user
cp systemd/aube-collect.* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now aube-collect.timer
loginctl enable-linger "$USER"     # pour que le timer tourne sans session ouverte
journalctl --user -u aube-collect  # journaux
```

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

Les tests tournent sans réseau, contre de faux serveurs (`tests/fake.py`). Ils
falsifient l'audit : un octet altéré, une annonce manquante ou une ligne d'index
supprimée doivent chacun être détectés.

## Phases

1. Collecte et archive ← *ici*
2. Tri par embeddings contre `profil.md`
3. Synthèse avec un modèle local standard (llama.cpp, API compatible OpenAI)
4. Boucle de retour et registre des signaux
5. Bascule sur le moteur déterministe (Rust)
