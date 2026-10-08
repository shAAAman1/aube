# Journal des décisions — Aube

Format : date, décision, raison, preuve (test ou mesure). Les chiffres viennent des
manifestes et des blobs de `data/`, sauf mention « sonde » (requête manuelle, conservée hors
dépôt).

## 2026-10-04 — Première confrontation de la phase 1 aux vrais flux

Contexte : premier contact avec les vrais flux, un dimanche (flux RSS arXiv vides). Six runs
ont été faits le même jour : 0156Z (antérieur à la session, User-Agent factice), 0215Z, 0237Z,
0240Z, 0246Z et 0303Z. Le dépôt n'a encore aucun commit, donc tous les manifestes portent
`"git": {}`. On ne peut plus retrouver le code exact de ces runs : seul `code_sha256` en garde
la trace.

### Hash de defusedxml : confirmé
- Décision : garder le hash du lock et mettre à jour son commentaire.
- Preuve : `pip download defusedxml==0.7.1 --no-deps` puis `sha256sum` donnent
  `a352e7e4…98a61`. C'est la valeur du lock et celle publiée par l'API JSON de PyPI.
  `pip install --require-hashes -r requirements.lock` passe dans un venv neuf.

### arXiv : abandon de l'API Atom, passage à OAI-PMH arXivRaw
- Constat :
  - l'API n'a qu'un filtre de date, `submittedDate` (manuel de l'API) ;
  - la requête `lastUpdatedDate:[…]` est réécrite en silence : le `<title>` de chaque blob
    `arxiv_api` archivé contient `submittedDate:"…"` ;
  - `totalResults` est exact pour la requête réécrite, donc `received == expected` passait
    alors qu'il manquait des articles ;
  - sur l'annonce hep-th du 2 octobre (sonde), l'API ne contenait aucun des 20 remplacements
    et 19 cross sur 20. Le cross manquant, 2610.00146, avait été soumis le 10 septembre.
- Décision (choix du propriétaire) : collecte par OAI-PMH, avec `metadataPrefix=arXivRaw` et un
  set par catégorie (sets vérifiés par `ListSets`, dont `physics:cond-mat:supr-con`).
  - Fenêtre : jours de datestamp clos, de (dernier succès − 3 j) à hier UTC.
  - Un jour par requête, et un élément par version listée.
- Preuve :
  - sur le blob réellement archivé (run 0246Z, hep-th), la datestamp 2026-10-02 contient
    35/35 nouveaux, 20/20 cross et 20/20 remplacements du listing officiel ;
  - test `test_arxiv_oai_reel` (2102.06878 v1→v5 et annonce tardive 2610.00146) ;
  - `test_remplacement_ancien_et_version_intermediaire` et `test_annonce_tardive_collectee`.
- Limites :
  - OAI ne fournit aucun total (`completeListSize` absent) : pour arXiv, le témoin RSS est le
    seul contrôle externe de complétude ;
  - le lien « datestamp = jour UTC d'annonce » n'est vérifié que sur hep-th, sur 1 jour.
- Point non rattrapé : l'OAI démarre au 2026-09-30. Les remplacements et annonces tardives de
  datestamp 09-28 et 09-29 ne sont couverts par aucune collecte fiable. Les fenêtres « arxiv »
  de l'ancienne API restent marquées complètes alors qu'elles ne le sont pas. C'est antérieur
  au premier jour qui peut compter pour le critère, mais à savoir.

### arXiv : un jour de datestamp par requête, et seconde passe au-delà d'une page
- Raison : le `resumptionToken` d'arXiv est sans état (`from` + `skip`, sonde). Si un
  enregistrement déjà servi change de datestamp pendant la pagination, la page suivante en
  saute un. Sur une fenêtre de rattrapage de plusieurs jours, la revue a reproduit une perte
  définitive avec une fenêtre déclarée complète.
- Preuve :
  - `test_glissement_de_pagination_rattrape_par_la_seconde_passe` (sans la seconde passe,
    2610.00010 est perdu, vérifié par mutation) ;
  - en réel, les totaux jour par jour (run 0303Z) sont identiques à ceux de la requête
    multi-jours (run 0246Z) : 162, 396, 468 et 66 versions.
- Coût : 4 requêtes par catégorie et par run (16 au total), contre 4 auparavant.

### CERN : URL du flux
- Constat : `https://home.cern/api/news/news/feed.rss` répond HTTP 404 (runs 0156Z et 0215Z).
  La page `https://home.cern/news` annonce `https://home.cern/feed/` (WordPress, RSS 2.0,
  10 items).
- Décision (choix du propriétaire) : lire `/feed/` et `/feed/?paged=2`, soit 20 items.
  - Raison : sur 3 semaines (sonde), il y a eu jusqu'à 7 articles entre deux runs à 00:40 UTC,
    pour une fenêtre de 10 ; un seul run manqué suffirait à perdre des articles.
  - Ne pas ajouter `/fr/feed/` : les traductions ont d'autres guid et d'autres liens.
- Empreinte de version : elle est stable. Les octets du flux varient d'une lecture à l'autre
  (le bloc calendrier `stringDate` dans `content:encoded`), mais `content:encoded` n'est pas
  haché. Les versions de « Want to develop your skills? » (`b4ac17ea0c12343e`) et de
  « Upcoming events » (`be8c26ce418ad0a0`) sont identiques sur 4 lectures de sonde et sur les
  runs 0237Z à 0303Z. Test : `test_cern_empreinte_ignore_le_calendrier_dynamique`.
- Audit : le contrôle de recoupement porte sur l'union des pages d'un run. Il exige aussi que
  le plus ancien élément lu ne soit pas plus récent que tout ce qui avait déjà été vu : un vieux
  billet re-daté (« Upcoming events », p=25536) fournissait un faux point commun.
  Tests : `test_cern_deux_pages_pas_de_faux_trou`,
  `test_cern_billet_re_date_ne_masque_pas_un_trou`.
- Reste à mesurer : de fausses révisions éventuelles sur plusieurs jours (re-datage de
  « Upcoming events »).

### INSPIRE : requête `da` validée
- Preuve :
  - le code source du parseur de requêtes INSPIRE fait correspondre `da` à `date-added`, qui
    devient `_created`, c'est-à-dire le champ `created` du hit ;
  - sur les 1480 hits archivés (2026-09-30 → 10-03), tous les `created` tombent dans la
    fenêtre : 571, 524 et 385 par jour, 0 le samedi ;
  - `da 2026-10-01` donne un total de 524, exactement le décompte des blobs, donc des jours
    entiers bornes incluses. Le fuseau UTC est déduit du code, pas observable : aucune création
    entre 20h et 02h UTC ;
  - `date-added` en toutes lettres renvoie HTTP 400, et `du` ramène 4930 anciens
    enregistrements.
- Décision : garder la requête. Contrôler les `control_number` distincts et la stabilité du
  total pendant la pagination.
  - Raison : pagination page/size sans instantané ; un glissement (doublon plus saut) passait
    pour une fenêtre complète.
  - Tests : `test_inspire_pagination_decalee_detectee`, `test_inspire_total_instable_detecte`.
- `earliest_date` est ajouté aux champs, puisque c'est la clé du tri `mostrecent`.
- Rattrapage après panne par tranches de 14 jours (`max_window_days`). Une fenêtre de plus de
  10 000 résultats (environ 24 jours de panne) échouait à chaque run sans jamais avancer.
  Test : `test_inspire_rattrapage_par_tranches`.
- Reste à mesurer : la dérive de l'index liée à `updated`. Aucune nouvelle version n'est
  apparue sur 6 runs rapprochés le même jour, alors que 74 % des enregistrements ont un
  `updated` daté du lendemain de leur création : il faut des runs quotidiens.

### Témoin RSS arXiv : format d'un flux rempli NON vérifié
- Observé : un canal vide le dimanche, `skipDays` samedi et dimanche,
  `lastBuildDate Sat, 03 Oct 2026 04:00:01 +0000`.
- Le flux est reconstruit à 04:00 UTC (minuit à New York), alors que le timer passe à
  00:40 UTC : chaque run lit le flux de la veille. Un run manqué, ou rattrapé après 04:00 UTC,
  fait perdre un jour de témoin sans que l'audit le voie.
- Le guid versionné (`oai:arXiv.org:XXXX.XXXXXvN`) et les `announce_type` ne sont que
  documentés (info.arxiv.org/help/rss_specifications.html).

### Audit
- `erreur_de_run` est limité aux `days` derniers jours (choix du propriétaire). Les manifestes
  ne sont jamais supprimés : sans cette borne, les deux erreurs 404 du 4 octobre auraient
  bloqué le critère pour toujours. Les deux erreurs de ce jour bloquent encore, à juste titre,
  jusqu'au 2026-10-17. Test : `test_erreur_de_run_bornee_a_la_fenetre`.
- L'audit ne plante plus sur un blob rejeté par le parseur, par exemple une page d'erreur OAI
  servie en HTTP 200. Il plantait à chaque lancement, et ce pour toujours. Le blob est ignoré
  si le run a annulé la source ; sinon il est signalé dans `blob_illisible`.
  Test : `test_audit_survit_a_un_blob_rejete`.
- Le témoin lu le jour J n'est jugé que quand l'OAI couvre J+1. La datestamp suit la dernière
  modification : un article remplacé le lendemain n'est moissonné qu'au run J+2, ce qui
  donnait de faux `temoin_absent` passagers.
  Tests : `test_audit_propre_puis_falsifications`, `test_temoin_lu_apres_reconstruction_du_rss`.
- Nouveau contrôle `temoin_inactif` : si une catégorie n'a aucune annonce lue dans le RSS sur
  au moins 7 jours couverts par l'archive, le critère est bloqué. Sinon, un changement de
  format du RSS (`parse_rss` renvoie `[]`) laissait passer ATTEINT avec 0 témoin vérifié.
  Test : `test_temoin_inactif_signale`. Risque connu : une fermeture d'arXiv d'une semaine
  (fêtes de fin d'année) le déclencherait.
- `source_en_retard` porte désormais sur les fenêtres OAI. OAI rend une fenêtre même le
  week-end, donc il n'y a plus de faux positif après un week-end sans annonce.

### http.py
- `Retry-After` est respecté (secondes ou date HTTP), et l'on attend le plus long du backoff
  et de l'en-tête. Au-delà de 600 s, on abandonne : l'échec est consigné puis rattrapé.
  Tests : `tests/test_http.py`. Aucun 503 n'a été observé sur environ 50 requêtes réelles.
- Les redirections hors https sont refusées. Cas observé :
  `https://home.cern/news/feed/` répond 301 vers `http://home.cern/feed/`.

### systemd : `TimeoutStartSec=1h`
- Raison : `http.py` peut attendre 600 s par `Retry-After`, avec 4 essais par requête. Sans
  plafond, un run bloqué pouvait durer indéfiniment (un service oneshot n'a pas de délai par
  défaut).
- Valeur : un run normal dure environ 2 min (de 70 à 139 s sur les 6 runs du 2026-10-04 ; 139 s
  pour 28 requêtes). 1 h tolère plusieurs attentes `Retry-After` maximales.
- Vérification : `systemd-analyze --user verify` sort à 0.
- Conséquence connue (traitée dans l'entrée suivante) : un run tué (SIGTERM au bout d'une
  heure) n'écrivait pas son manifeste. Or les sources déjà validées sont commitées dans l'index : leurs éléments n'ont
  alors aucun manifeste. Pour arXiv et INSPIRE, le recouvrement les ré-archive au run suivant
  (scénario rejoué par la revue). Pour CERN, un élément sorti du flux entre-temps laisserait
  un `index_non_rejouable` permanent. Piste : intercepter SIGTERM pour écrire un manifeste
  `interrupted` avant de sortir.

### collect : SIGTERM écrit le manifeste (`status: interrupted`)
- Raison : sans manifeste, les éléments des sources déjà validées restaient dans l'index sans
  données primaires qui les justifient (voir l'entrée précédente).
- Mécanisme :
  - le handler lève `Interrupted`, une BaseException : le « une source en panne n'arrête pas
    les autres » ne l'absorbe donc pas ;
  - la source en cours est annulée (rollback) et consignée en erreur ; les sources restantes
    sont listées dans `not_run` ;
  - un second SIGTERM pendant la finalisation est ignoré ;
  - Ctrl-C suit le même chemin ;
  - code de sortie 1.
- Preuves :
  - tests avec un vrai `os.kill(SIGTERM)` envoyé au milieu d'une source :
    `test_sigterm_ecrit_le_manifeste_et_garde_l_index_rejouable`,
    `test_sigterm_liste_les_sources_non_lancees`, `test_ctrl_c_suit_le_meme_chemin` ;
  - 5 mutations détectées (sans handler, c'est pytest lui-même qui est tué) ;
  - essai réel sur une copie de `data/` : `python -m aube collect` contre les vrais flux, tué
    au bout de 20 s. On obtient un manifeste `interrupted`, hep-ex conservé avec sa fenêtre,
    hep-ph annulé, 9 sources dans `not_run` et un audit sans `index_non_rejouable`.
- Limite : un signal reçu avant la boucle des sources (création de la ligne `runs`) ou pendant
  un rollback n'est pas couvert. Aucun élément n'est alors orphelin, sauf dans le second cas.

### audit : `cern_trou_possible` et `temoin_absent` bornés à la fenêtre du critère
- Décision du propriétaire : comme `erreur_de_run`, ces problèmes ne bloquent que s'ils datent
  des `days` derniers jours.
  - Date retenue : `run_id` pour un trou CERN ; `fetched_at` de la lecture RSS pour un témoin
    (`temoin_absent` et `temoin_version_absente`).
  - Les plus anciens sont rangés dans `hors_fenetre` (qui remplace `erreurs_hors_fenetre`),
    affichés et non bloquants.
- Raison : un trou CERN ne se rattrape pas (flux glissant), et les manifestes ne sont jamais
  supprimés. Sans borne, un seul incident rendait le critère inatteignable pour toujours,
  alors que le critère porte sur « 14 jours consécutifs sans perte ».
- Ce que cela implique : une perte réelle de plus de 14 jours (un article annoncé et jamais
  archivé) n'empêche plus ATTEINT. Elle reste visible dans `hors_fenetre`, et il faut la lire.
- Restent non bornés, car ils décrivent l'état actuel de l'archive : `blob_manquant`,
  `hash_invalide`, `blob_illisible`, `index_non_rejouable`, les doublons, `trou_de_fenetre`,
  `source_en_retard` et `temoin_inactif`.
- Preuves : `test_trou_cern_et_temoin_absent_bornes_a_la_fenetre` (non bloquants à 14 jours,
  bloquants à 16) ; 5 mutations de la borne détectées.

## Volume disque (mesuré le 2026-10-04 après le run 0303Z)

| | octets |
|---|---|
| `data/` total | 12 350 842 (13 Mo) |
| `data/blobs` (78 blobs) | 11 006 149 |
| `data/manifests` (6) | 62 645 |
| `data/aube.sqlite` | 1 282 048 (1001 arxiv, 20 cern, 1480 inspire) |

Nouveaux blobs (gzip) par run avec la configuration actuelle (runs 0246Z et 0303Z) : environ
**2,0 Mo par run**.
- INSPIRE : 1,53 Mo. L'ordre des clés JSON varie d'une réponse à l'autre, donc les blobs ne se
  dédupliquent jamais, même à contenu identique.
- arXiv OAI : 0,45 Mo.
- CERN : 0 à 40 ko, car il n'y a que 2 versions du flux en cache côté serveur.

Projection naïve : environ 0,7 Go par an. **Ce n'est pas encore une croissance quotidienne
mesurée** : tous les runs datent du même dimanche. À remesurer après 7 runs quotidiens, en
semaine.

## 2026-10-08 — Récupération du travail du 4 octobre, principe de référence, premier run depuis 4 jours

### Incident : quatre fichiers écrasés le 5 octobre à 01:21
- Constat : `aube/audit.py`, `aube/__main__.py`, `tests/test_phase1.py` et `README.md` étaient
  revenus à leur version d'avant la session du 4 octobre, plus un correctif « référence »
  (`aube/ref.py`, contrôle `reference_irresoluble`, commande `ref`, 2 tests). Les autres fichiers
  (collect, parseurs, http, config, systemd) avaient bien l'état final du 4 octobre.
  Effet : 8 tests sur 27 en échec, `python -m aube audit` plantait sur `KeyError: 'arxiv_oai'`
  dès le run 0246Z. Le dépôt n'a toujours aucun commit, donc aucun historique à consulter.
- Récupération : l'état final du 4 octobre survivait dans un arbre git orphelin
  (`7027cba0`, écrit par la session du 4 octobre pour préparer les patches). Preuve que cet
  arbre est le bon : les 13 patches de `~/aube-commits/`, rejoués sur l'index, donnent
  exactement l'arbre `7027cba0`. Les 4 fichiers ont été restaurés depuis cet arbre par le
  propriétaire (`git cat-file -p <blob> > fichier`), puis le correctif référence a été
  réappliqué par-dessus. Les versions écrasées restent dans l'index git et dans le
  correctif extrait (`14-reference.patch`).
- Leçon : des objets orphelins sont supprimés par `git gc` après deux semaines. Tant que le
  commit initial signé n'est pas fait, le travail n'est protégé par rien. **Faire les commits.**

### Principe de référence (patch 14)
- `aube/ref.py` résout élément → source publique → blob SHA256 (re-parsé, doit contenir
  l'élément) → manifeste (URL, date, commit, hash du code). `python -m aube ref arxiv:<id>v<n>`
  sort 1 si un maillon casse.
- L'audit contrôle chaque ligne de l'index (`reference_irresoluble`).
- Tests : `test_reference_resolue_jusqu_au_blob`, `test_reference_falsifiee_detectee`.
  Total : 48 tests, tous verts, y compris sur l'état rejoué des 14 patches.
- Vérifié en réel : `ref arxiv:1205.5754v1` (élément du run 0016Z) se résout jusqu'à l'URL
  OAI du 2026-10-06, `commit: null` puisqu'il n'y a pas encore de commit.

### Run réel 20261008T0016Z (manuel, le timer n'est pas installé)
- 48 requêtes OK, 0 erreur, 3 min 14 s (00:16:24 → 00:19:37 UTC). Fenêtres : arXiv OAI et
  INSPIRE du 2026-09-30 au 2026-10-07 (dernier succès 10-03 − 3 j de recouvrement), CERN 2 pages.
- Reçus : hep-ex 338, hep-ph 801, hep-th 1033, cond-mat.supr-con 131 versions ; INSPIRE 2487
  en 10 pages. Index : arxiv 1001 → 2007, cern 20 → 23, inspire 1480 → 2707.
- Aucun jour n'a dépassé une page OAI (32 requêtes = 8 jours × 4 sets, pas de seconde passe).
- Audit après le run : seul problème, les 2 erreurs 404 CERN du 4 octobre, bloquantes
  jusqu'au 2026-10-17 inclus. Pas de `trou_de_fenetre`, pas d'`index_non_rejouable`, pas de
  `reference_irresoluble` sur 4737 éléments. Témoins vérifiés : 0, attendu (le témoin lu le
  jour J n'est jugé que quand l'OAI couvre J+1).
- Disque : 48 nouveaux blobs, 3,67 Mo gz (INSPIRE 2,58 Mo, arXiv OAI 0,92 Mo, RSS 0,13 Mo,
  CERN 0,04 Mo). `data/` : 12,35 → 17,25 Mo. Ce run couvrait 8 jours ; la croissance
  quotidienne reste à mesurer sur des runs quotidiens.
- Les 4 jours sans run (4 → 7 octobre) n'ont rien perdu côté arXiv OAI et INSPIRE (fenêtres
  reprises au dernier succès). Côté CERN, 3 nouveaux éléments et recoupement OK, mais un trou
  CERN sur une absence plus longue ne se rattrape pas : c'est la raison d'installer le timer.

### Décisions en attente du propriétaire
- Installer et activer le timer (`systemctl --user enable --now`, plus `loginctl enable-linger`
  pour qu'il tourne sans session ouverte). Le plan du 5 octobre (veille générique, V-Dem,
  AGPL, code en anglais) disait « avant d'activer le timer » ; CLAUDE.md dit phase 1 physique
  sans licence. Tant que ce n'est pas tranché, les 14 jours ne commencent pas.
- Faire le commit initial signé puis `sh ~/aube-commits/apply.sh` (14 étapes, tests à chaque
  étape).

### Timer activé, premier run automatique
- 15 commits signés (clé FIDO, `git log --format=%G?` : tous `G`) : l'arbre T13 et le patch 14
  sont désormais protégés par l'historique. `user.email` du dépôt réglé sur l'adresse de
  `allowed_signers`.
- Unités copiées dans `~/.config/systemd/user/`, `enable --now` à 02:36 CEST, `Linger=yes`
  était déjà actif.
- Run `20261008T0040Z` lancé par le timer à 02:40:02 CEST : 27 requêtes OK, 0 erreur, 1 min 30 s,
  38 Mo de mémoire au pic. Le manifeste porte enfin un commit (`e6e7057`, `dirty: false`).
  Rien de neuf dans l'index, attendu : la fenêtre (10-05 → 10-07) venait d'être moissonnée
  par le run manuel 0016Z.
- Audit inchangé : seules les deux 404 CERN du 4 octobre bloquent. Si les runs quotidiens
  restent propres, la fenêtre de 14 jours les laissera sortir le 18 octobre et le critère peut
  être atteint au plus tôt le **21 octobre** (14 jours consécutifs depuis le 8).
- Prochaine échéance : 2026-10-09 02:40 CEST.

### Licence : AGPL-3.0-or-later
- Décision du propriétaire (« licence libre »), conforme à son choix du 5 octobre. Jusqu'ici le
  dépôt n'avait aucune licence, donc tous droits réservés.
- Texte : copie canonique de Debian `/usr/share/common-licenses/AGPL-3.0`, SHA256 consigné
  dans le message de commit. `pyproject.toml` : `license = "AGPL-3.0-or-later"`.
- La licence porte sur le code. Les données de `data/` ne sont pas redistribuées et gardent
  les conditions de leurs sources.
- Dépôt poussé sur GitHub (privé) : `git@github.com:shAAAman1/aube.git`, `main` = `3f24000`,
  17 commits signés ; GitHub détecte la licence AGPL-3.0. Pas de Gitea sur le Bixeon pour
  l'instant (rien d'installé) : le plan du 5 octobre le prévoyait après le critère de phase 1.
- Dépôt rendu **public** le même jour (décision du propriétaire, « licence libre »). Avant
  l'ouverture : `git grep` sur toutes les révisions, hors LICENSE et fixtures, pour adresses
  e-mail, mots de passe, jetons et clés. Seul résultat : `toi@example.org` dans
  `config.local.toml.example`. Les fixtures contiennent deux adresses publiques des flux
  (`rss-help@arxiv.org`, `bulletin-editors@cern.ch`). `config.local.toml` et `data/` n'ont
  jamais été committés.
