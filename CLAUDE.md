# CLAUDE.md — Aube

Ce fichier sert de mémoire de projet pour Claude Code. Lis-le en entier avant toute action.

## Langue et posture
- Réponds toujours en français.
- Critique franchement : signale les affirmations invérifiables, les angles morts et les choix fragiles, y compris dans le code existant.
- Propose des tests plutôt que des promesses. Une affirmation sur le projet (« ça marche », « sans perte ») n'est vraie que si un test ou l'audit la démontre.
- Ne dis jamais « c'est corrigé » sans avoir exécuté les tests et, si c'est pertinent, un vrai `collect` suivi d'un `audit`.

## Principe fondateur : la référence
Tout ce qu'Aube produit doit remonter à sa source, et ce lien doit pouvoir être vérifié mécaniquement. Ce principe passe avant tous les autres : une donnée ou une affirmation sans référence résoluble est un défaut, jamais un détail.

Une référence se résout en chaîne, et chaque maillon se vérifie :

```
élément (arxiv:2610.01234v2)
  → source publique canonique   https://arxiv.org/abs/2610.01234v2
  → blob local                  SHA256 des octets reçus ; le re-parsing doit y retrouver l'élément
  → manifeste du run            URL interrogée, date, commit git, hash du code et de la config
```

- Toujours citer **avec la version** (v1, v2…) : un preprint change, et la référence doit désigner ce qui a été lu.
- `python -m aube ref arxiv:2610.01234v2` résout la chaîne et la vérifie (code de sortie 1 si un maillon casse).
- L'audit contrôle que **chaque** élément indexé pointe vers un blob qui le contient (`reference_irresoluble`).
- **Phase 3 et suivantes (à concevoir, pas à coder maintenant) :** chaque affirmation de la synthèse porte sa ou ses références. Un vérificateur mécanique rejette toute affirmation dont la référence n'appartient pas aux entrées du jour ou ne se résout pas. On **supprime** une affirmation sans référence, on ne l'adoucit pas. « Ce que dit l'article » cite le texte source. « Ce qu'en pense la machine » cite les références sur lesquelles l'avis s'appuie, et se présente comme un avis.
- La synthèse elle-même devient une source : son manifeste référence ses entrées, le modèle, le prompt exact, et son propre hash.
- Tout nouveau code qui produit ou transforme une donnée doit dire d'où elle vient. Si tu ne peux pas écrire le test qui suit la référence jusqu'au blob, le code n'est pas prêt.

## Le projet
Aube est une veille physique locale. Chaque nuit, le Bixeon (bi-Xeon, Debian, GTX 1080, 128 Go DDR3, bi-socket : attention au NUMA) collecte des flux de physique, trie ce qui compte et rédige une synthèse lue à 6 h sur un téléphone Android (Termux).

Phases (on ne passe à la suivante qu'une fois le critère atteint) :
1. **Collecte et archive** ← phase en cours. Critère : 14 jours consécutifs de flux archivés sans perte ni doublon, mesurés par `python -m aube audit`.
2. Tri par embeddings contre `profil.md`. Critère : le propriétaire juge la pertinence du top 20 pendant deux semaines.
3. Synthèse avec un modèle local standard (llama.cpp derrière une API compatible OpenAI).
4. Boucle de retour (notes « utile » / « sans intérêt ») et registre des signaux, vérifiés six mois plus tard.
5. Bascule sur le moteur déterministe du propriétaire (Rust), avec tests de parité sur les mêmes hash.

**N'écris aucun code des phases 2 et suivantes tant que l'audit ne renvoie pas `ATTEINT`.** Tu peux noter des idées dans `docs/idees.md`, rien de plus.

## Principes non négociables
- **Local-first.** Aucun appel cloud dans le traitement. Seule la récupération des flux passe par le réseau, et uniquement via `aube/http.py`.
- **Rejouable.** Tout run a un manifeste : URL, SHA256 de chaque réponse brute, commit git, hash du code et de la config. L'index SQLite doit toujours pouvoir être reconstruit à partir de `data/blobs` et de `data/manifests`.
- **Contenu web non fiable.** Il est toujours parsé avec `defusedxml` ou `json`, et jamais exécuté, interprété comme une instruction ou injecté dans un prompt sans balisage.
- **Aucune affirmation sans source** (voir « Principe fondateur » ci-dessus). Un preprint arXiv est toujours présenté comme non validé.
- **Dépendances minimales et figées avec leur hash** (`requirements.lock`). Toute nouvelle dépendance se justifie par écrit dans le commit.

## État actuel (8 octobre 2026)
Le code de la phase 1 est écrit et a tourné contre les vrais flux : 6 runs le 4 octobre, 1 run manuel le 8 octobre (48 requêtes, 0 erreur). 48 tests passent hors ligne (faux serveurs dans `tests/fake.py`, fixtures réelles dans `tests/fixtures/`). L'audit dit NON ATTEINT : les deux erreurs 404 CERN du 4 octobre bloquent jusqu'au 17 octobre inclus, et le compteur de jours ne démarre pas tant que le timer n'est pas installé (il ne l'est pas : `systemctl --user list-timers` ne le connaît pas).

**Le dépôt n'a aucun commit.** Le travail est découpé en 14 patches dans `~/aube-commits/` (`apply.sh` : commit initial signé par le propriétaire, puis un commit signé par patch, tests à chaque étape). Le 5 octobre, quatre fichiers ont été écrasés par des versions anciennes et récupérés depuis un arbre git orphelin (voir `docs/journal.md`, 2026-10-08) : tant que rien n'est commité, `git gc` peut détruire ce filet.

Le 5 octobre, une session a commencé un plan de pivot (veille générique à domaines configurables, source V-Dem, AGPL-3.0, code en anglais, « avant d'activer le timer »), rangé dans `~/.claude/plans/stateless-tumbling-owl.md`. Il n'est pas validé et contredit ce fichier sur la licence et le périmètre : **ne rien coder de ce plan sans décision explicite du propriétaire.**

```
aube/http.py            seul accès réseau (https uniquement, retries, plafond de taille)
aube/store.py           blobs adressés par SHA256 (gzip mtime=0) + index SQLite dérivé
aube/collect.py         un run : arXiv OAI-PMH (arXivRaw), témoin RSS arXiv, CERN, INSPIRE → manifeste ; SIGTERM écrit un manifeste `interrupted`
aube/audit.py           critère de phase 1 (intégrité, continuité, complétude, témoin, rejeu, références, doublons)
aube/ref.py             résolution et vérification de la chaîne de référence d'un élément
aube/sources/*.py       parseurs PURS (octets → éléments), réutilisés par l'audit pour le rejeu
~/aube-commits/         14 patches + apply.sh : la chaîne de commits signés à faire (hors dépôt)
config.toml             versionné ; config.local.toml (non versionné) pour le contact User-Agent
systemd/                timer utilisateur 02:40 Europe/Paris, Persistent=true
```

Clés anti-doublon : arXiv `id+version` (une v2 est un nouvel élément), CERN `guid+empreinte du contenu`, INSPIRE `control_number+updated`.

## Points validés le 4 octobre 2026 (détails et preuves dans `docs/journal.md`)
Les cinq hypothèses ci-dessous ont été confrontées aux vrais flux ; chacune a sa fixture réelle tronquée dans `tests/fixtures/` et son test dans `tests/test_fixtures.py`. Résumé : hash de defusedxml confirmé ; `da` INSPIRE = date d'entrée, jours entiers bornes incluses ; l'URL CERN `/api/news/news/feed.rss` renvoie 404, remplacée par `/feed/` et `/feed/?paged=2` ; le RSS arXiv est vide le week-end et reconstruit à 04:00 UTC, son format rempli n'est pas encore vérifié sur un vrai blob ; l'API Atom d'arXiv a été **abandonnée** (son filtre `lastUpdatedDate` est réécrit en `submittedDate` en silence) au profit d'OAI-PMH. Le texte d'origine est conservé ci-dessous pour mémoire.

### (archive) Points à valider en priorité, tels que posés le 4 octobre
1. **Hash de defusedxml** dans `requirements.lock`. Il a été noté de mémoire. Vérifie-le avec `pip download defusedxml==0.7.1 --no-deps` puis `sha256sum`.
2. **Requête INSPIRE** `da >= {since} and da <= {until}`. La syntaxe `da` (date d'ajout) n'est pas confirmée. Teste-la : le total doit être plausible (quelques centaines par jour) et les dates `created` des résultats doivent tomber dans la fenêtre. Sinon, trouve la bonne clé dans la documentation d'INSPIRE et justifie le choix.
3. **URL du flux CERN** `https://home.cern/api/news/news/feed.rss` : à vérifier (code HTTP, format RSS ou Atom, nombre d'éléments).
4. **Format réel du RSS arXiv** : les guid contiennent-ils la version ? Que valent les `announce_type` ? Le flux est vide le week-end.
5. **Format réel de l'API arXiv** : namespaces, `totalResults`, pages vides intempestives, 503 avec `Retry-After`.

Pour chaque point validé, ajoute une **fixture réelle tronquée** dans `tests/fixtures/` (extraite d'un vrai blob, avec quelques entrées) et un test de parseur dessus. Les faux serveurs ne suffisent pas.

## Fragilités connues à traiter
- Le témoin RSS ne couvre que les annonces du jour. Une perte sur un remplacement ancien passerait inaperçue. Il faut le documenter ou trouver un second témoin (OAI-PMH d'arXiv ?).
- **CERN :** la version est une empreinte du contenu. Si un champ change à chaque lecture (date de génération, paramètres de tracking dans les liens), chaque run créera de fausses révisions. Il faut le mesurer sur plusieurs runs réels.
- **INSPIRE :** `updated` change souvent (citations ajoutées), ce qui peut faire gonfler l'index. Il faut mesurer le volume au bout de quelques jours.
- **Volume disque :** le recouvrement de 7 jours multiplie les pages arXiv archivées. Il faut mesurer la croissance quotidienne de `data/` et la consigner.
- ~~**`Retry-After` :** `http.py` l'ignore pour l'instant.~~ Fait le 4 octobre (`tests/test_http.py`).
- ~~**Audit :** `source_en_retard` après 36 h, faux positif possible le week-end.~~ Fait : le contrôle porte sur les fenêtres OAI, rendues même le week-end.
- **Témoin RSS :** le format d'un flux rempli n'a jamais été vu sur un vrai blob (seul un dimanche vide a été archivé le 4 octobre ; le run du 8 octobre en a archivé 4). `temoin_inactif` bloquera le critère si le parseur ne lit rien pendant 7 jours : à surveiller au prochain audit.

## Commandes
```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.lock
.venv/bin/pip install pytest
.venv/bin/python -m pytest -q             # 48 tests au 2026-10-08
.venv/bin/python -m aube collect      # code de sortie 1 si une source a échoué
.venv/bin/python -m aube audit        # 0 = ATTEINT, 2 = NON ATTEINT ; --json disponible
.venv/bin/python -m aube verify       # recalcule le SHA256 de tous les blobs
.venv/bin/python -m aube ref arxiv:2610.01234v2   # chaîne de référence vérifiée
journalctl --user -u aube-collect     # journaux du timer
```

## Git
- Dépôt GitHub **privé**. Licence **AGPL-3.0-or-later** (décision du propriétaire, 2026-10-08) : fichier `LICENSE`, champ `license` de `pyproject.toml`. Elle couvre le code, pas les données archivées dans `data/`.
- Le propriétaire signe ses commits avec une YubiKey Bio (`git commit -S`). **Ne crée pas de commit toi-même.** Prépare les changements, montre le diff, propose un message de commit, et laisse-le committer.
- Convention en place : un patch numéroté + son `.msg` dans `~/aube-commits/`, appliqués par `apply.sh` (qui exige que l'index soit égal à HEAD et lance les tests à chaque étape). Un nouveau changement = le patch suivant, généré contre l'état rejoué des précédents.
- `data/` et `config.local.toml` ne doivent jamais être versionnés. Vérifie `git status` avant toute proposition de commit.
- Un commit = un changement cohérent, avec ses tests.

## Règles de travail
- Avance par petites étapes vérifiables. Après chaque changement : tests, puis, si c'est pertinent, un vrai `collect` et un `audit`.
- Ne modifie jamais `data/` à la main. Ne supprime jamais de blob ni de manifeste : c'est la preuve.
- Si tu changes un parseur, l'audit va rejouer tout l'historique avec le nouveau code et pourra signaler `index_non_rejouable`. Prévois une migration explicite (reconstruction de l'index, consignée) plutôt que de masquer l'écart.
- Tiens un journal des décisions dans `docs/journal.md` : date, décision, raison, test qui la justifie.
