# Migration vers Cloudflare R2 et dernière actualisation

Ce correctif est préparé à partir de l’archive GitHub fournie le 29 septembre 2026. Il modifie le stockage, complète la chaîne GitHub Actions et réserve la dernière actualisation au **1er octobre 2026 à 05:17 UTC (07:17 à Paris)**. Le mois collecté sera **septembre 2026**. Aucun compte distant n’a été modifié pendant la préparation.

## 1. Préparer Cloudflare

Dans Cloudflare R2, créer un bucket **privé**, de classe **Standard**, nommé `prospection-b2b`. Ne pas activer d’accès public.

Créer des identifiants S3 R2 avec lecture et écriture des objets, limités à ce bucket, pour la migration et GitHub Actions. Relever :

- l’endpoint S3 du compte, tel que `https://IDENTIFIANT_COMPTE.r2.cloudflarestorage.com` (copier la valeur fournie par Cloudflare, y compris une éventuelle juridiction) ;
- l’Access Key ID et la Secret Access Key. Ce sont les identifiants S3 R2, pas un jeton Bearer Cloudflare.

Pour Streamlit, utiliser de préférence une seconde paire limitée à la **lecture** du même bucket. Ne jamais publier ces valeurs dans GitHub ou dans une conversation.

R2 remplace uniquement le stockage S3. Streamlit reste hébergé sur Streamlit Community Cloud et le CRM reste dans Neon.

## 2. Installer le correctif

Dans GitHub Actions, désactiver provisoirement l’ancien workflow mensuel, et attendre la fin de toute exécution en cours. La source ne doit pas changer pendant la copie.

Dans le terminal du projet :

```bash
cd /Users/maussangceline/Documents/jedha_exercices/prospection-b2b
source /Users/maussangceline/.venvs/prospection-b2b/bin/activate
git status
```

Sauvegarder ou committer tes éventuelles modifications locales avant de remplacer des fichiers. L’archive fournie contient uniquement les fichiers nouveaux ou modifiés, avec leur arborescence. Depuis la racine du projet, si elle se trouve dans Téléchargements :

```bash
unzip -o "$HOME/Downloads/prospection_b2b_r2_patch.zip" -d .
```

Cette commande inclut le fichier `.github/workflows/monthly-data.yml`, même s’il est caché dans le Finder. Elle ne touche pas `.env`, aux données locales ni aux secrets Streamlit. Les fichiers `*_s3.py` gardent leur nom pour préserver les commandes existantes ; ils utilisent maintenant R2.

Les dépendances de l’archive d’origine sont conservées. Dans ton environnement habituel :

```bash
python -m pip install -r requirements-pipeline.txt -r dashboard/requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
```

## 3. Configurer la migration locale

Ajouter au `.env` existant ces quatre lignes avec tes vraies valeurs :

```dotenv
R2_ENDPOINT_URL=https://IDENTIFIANT_COMPTE.r2.cloudflarestorage.com
R2_ACCESS_KEY_ID=IDENTIFIANT_R2
R2_SECRET_ACCESS_KEY=SECRET_R2
R2_BUCKET_NAME=prospection-b2b
```

**Conserver provisoirement** les variables AWS actuelles et `S3_BUCKET_NAME=prospection-b2b-cmaussang-2026`. Seul le script de migration les utilise encore pour lire la source. Garder également les paramètres INSEE et Neon.

Inventaire sans modification :

```bash
python migrate_s3_to_r2.py
```

Puis sauvegarde et copie :

```bash
python migrate_s3_to_r2.py --copy
```

Le dernier inventaire connu comportait 3 900 objets pour 325,20 Mo ; le script relève le volume réel au moment du lancement.

Le script :

1. sauvegarde chaque objet courant sous `data/backup_s3_r2/objects/` ;
2. conserve sa clé d’origine dans R2 ;
3. relit chaque objet R2 et compare son empreinte SHA-256 ;
4. refuse d’écraser un objet R2 déjà présent avec un contenu différent ;
5. vérifie que l’inventaire AWS n’a pas changé pendant la copie ;
6. écrit `data/backup_s3_r2/manifest.json`, avec le statut final `terminee`.

Les noms des fichiers de sauvegarde sont des empreintes : le manifeste relie chacun à sa clé d’origine. Garder ensemble le manifeste et le dossier `objects`, idéalement aussi sur un support de sauvegarde indépendant.

Une interruption peut être suivie d’une relance de la même commande : les objets identiques déjà copiés ne sont pas réécrits. **Ne pas relancer cette migration après l’actualisation finale**, car R2 contiendra alors de nouvelles données différentes de la source AWS.

Le script ne supprime rien dans AWS. Il inventorie les anciennes versions S3 si les droits le permettent, mais ne les copie pas. Si des anciennes versions existent ou si leur inventaire est impossible, les examiner et sauvegarder celles à conserver avant de fermer AWS.

## 4. Vérifier les données existantes sur R2

```bash
python check_r2.py
```

Ce contrôle lit les trois référentiels COG et le Parquet publié ; il vérifie son empreinte et les 19 colonnes indispensables au dashboard. Il ne collecte, ne recalcule et ne publie rien.

Tester ensuite Streamlit avec R2 :

```bash
DATA_SOURCE=s3 python -m streamlit run dashboard/app.py
```

**`DATA_SOURCE=s3` est volontaire** : c’est le nom du mode de lecture via le protocole S3, également utilisé par R2. Le mode `local` continue à lire DuckDB.

## 5. Configurer Streamlit et GitHub

Dans les secrets de l’application Streamlit, ajouter les quatre variables `R2_*` (avec les identifiants de lecture). Conserver :

```toml
DATA_SOURCE = "s3"
S3_SCORES_KEY = "processed/prospects/current.parquet"
```

Conserver aussi `CRM_DATABASE_URL` et les autres réglages utiles. Ne pas remplacer l’ensemble des secrets par ce seul extrait. Les nouveaux scripts n’utilisent plus les variables AWS du dashboard.

Dans GitHub → Settings → Secrets and variables → Actions, ajouter :

- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`

Conserver `INSEE_API_KEY`. Le nom `prospection-b2b` est défini dans le workflow. Les anciens secrets AWS ne sont plus utilisés par celui-ci.

Publier les fichiers du correctif (la liste exacte est dans `FICHIERS_MODIFIES.txt`). Depuis le projet :

```bash
python - <<'PY'
from pathlib import Path
import subprocess
files = Path('FICHIERS_MODIFIES.txt').read_text().splitlines()
subprocess.run(['git', 'add', '--', *files, 'FICHIERS_MODIFIES.txt'], check=True)
PY
git diff --cached --stat
git commit -m "Migration R2 et actualisation unique du 1er octobre 2026"
git push origin main
```

Ces commandes ne sélectionnent ni `.env` ni les sauvegardes. Après le redéploiement, cliquer sur « Actualiser les données » dans Streamlit pour vider son cache. Vérifier l’affichage et le suivi commercial.

**Réactiver le workflow** sur GitHub après la configuration, avant le 1er octobre. Il doit être présent dans la branche par défaut `main`. Un lancement manuel avant cette date affichera simplement une date non autorisée : ce n’est pas un test complet de la collecte.

## 6. Fonctionnement de la dernière actualisation

Le 1er octobre, la chaîne :

1. vérifie la date exacte et l’absence de publication finale déjà réussie ;
2. récupère les référentiels COG depuis R2 ;
3. collecte septembre 2026 et archive les réponses ;
4. reconstruit DuckDB depuis les collectes historiques de R2 ;
5. charge les codes postaux, vérifie l’activité, puis collecte BODACC, les mouvements et le capital ;
6. exécute les transformations et tests dbt avec `date_evaluation=2026-10-01` ;
7. publie le Parquet vérifié dans R2 ;
8. écrit `control/updates/2026-10-01.success.json` ;
9. demande la désactivation du workflow.

Le cron n’exprime pas l’année : le contrôle de date la vérifie explicitement. Même si la désactivation est refusée par GitHub, aucun traitement de données ne sera autorisé après le 1er octobre 2026. Le marqueur empêche une nouvelle publication réussie ce même jour. Si le processus s’arrête entre la publication et l’écriture du marqueur, le garde reconnaît le Parquet final par ses métadonnées et son empreinte et termine l’enregistrement sans recommencer la collecte.

En cas d’échec avant publication, une relance manuelle reste possible **le 1er octobre uniquement**. Les étapes déjà tentées peuvent alors être répétées ; l’objectif est une publication finale réussie unique. Après cette date, une intervention explicite sur le code serait nécessaire pour autoriser une reprise. Les scripts locaux restent des outils manuels : ne pas les relancer pour publier de nouvelles données après le gel.

GitHub peut retarder ou manquer un lancement planifié. Vérifier Actions le 1er octobre ; si nécessaire, lancer « Run workflow » ce jour-là. Aucun mécanisme ne peut garantir la réussite d’API externes à heure fixe. De même, un instantané au 1er octobre ne peut inclure les créations de septembre publiées tardivement par les sources.

Une fois terminé, Streamlit reste consultable et le CRM peut toujours enregistrer des notes dans Neon. Seules les données de prospection sont figées.

## 7. Quitter AWS après validation

Attendre la copie vérifiée, le contrôle de Streamlit **et le succès du 1er octobre**. Conserver la sauvegarde locale et son manifeste. Examiner les anciennes versions S3, puis les autres ressources et la facturation AWS avant de fermer le compte. La fermeture AWS n’est pas exécutée par ce correctif.

Après validation, retirer les anciens secrets AWS de GitHub, Streamlit et du `.env`, puis révoquer les identifiants AWS. Garder les identifiants R2 de lecture de Streamlit. Les accès R2 d’écriture de GitHub peuvent être révoqués après la dernière publication si aucun autre usage ne les nécessite.

## Vérifications effectuées à la préparation

- 93 tests Python réussis, dont 14 tests de migration et de garde de publication.
- Compilation des fichiers Python.
- Tests avec stockage simulé : reprise sans écrasement, différence de contenu, accès refusé, mauvaise empreinte, dates interdites et récupération après publication.
- Aucun accès réel à AWS, R2, INSEE ou Neon ; aucune collecte réelle et aucun déploiement effectués ici.
- Les tests dbt sur tes données réelles restent exécutés par le workflow avant publication. La validation locale a utilisé les dépendances disponibles dans l’environnement de préparation ; les versions déclarées dans ton dépôt ont été conservées.

Documentation officielle :

- https://developers.cloudflare.com/r2/get-started/s3/
- https://developers.cloudflare.com/r2/api/s3/api/
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
