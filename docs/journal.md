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
