# Tableau de bord et actualisation mensuelle

## 1. Installer dans le projet existant

Copier le contenu de cette archive à la racine de `prospection-b2b` en conservant les sous-dossiers. Le dossier `.github` est masqué sur macOS : Cmd + Maj + . permet de le voir dans le Finder.

Aucun fichier du pipeline existant n'est remplacé. Conserver les scripts `collect_sirene.py`, `upload_raw_s3.py`, `load_raw_duckdb.py` et tous les modèles dans `dbt_prospection`. Les versions des scripts adaptées à août 2025 sont requises.

L'application utilise les colonnes `nom_affiche`, `libelle_age` et les scores déjà validés. Les requêtes de scoring restent dans dbt. Elle n'effectue aucune collecte.

## 2. Démarrer sur le Mac

Depuis le terminal situé à la racine du projet :

```bash
source "$HOME/.venvs/prospection-b2b/bin/activate"
python -m pip install -r dashboard/requirements.txt
python -m streamlit run dashboard/app.py
```

La base `data/warehouse/prospection.duckdb` est détectée automatiquement. Le navigateur s'ouvre normalement sur http://localhost:8501. Si nécessaire, ouvrir cette adresse manuellement.

Les données sont lues puis la connexion DuckDB est fermée. Terminer les commandes de chargement/dbt avant de cliquer sur « Actualiser les données ». Le cache dure au maximum cinq minutes.

Les indicateurs portent sur la sélection filtrée. Tous les âges sont visibles par défaut. Les noms absents utilisent le SIRET ; les codes postaux masqués affichent « Non diffusé ». Les établissements d'un an et plus sont visibles, sans score ni couleur. La date d'évaluation et la période couverte sont affichées.

Le fichier CSV contient la sélection triée, séparateur point-virgule et encodage UTF-8 avec BOM. À l'import dans Excel, choisir le type texte pour le SIRET afin de conserver ses 14 chiffres.

## 3. Publier le premier résultat dans S3

Pour conserver la date de la démonstration :

```bash
dbt build --project-dir dbt_prospection --profiles-dir dbt_prospection --vars '{"date_evaluation": "2026-09-22"}'
```

Après réussite de tous les tests :

```bash
python export_scores_s3.py
```

Ce script lit le `.env` existant. Il vérifie le volume, l'unicité des SIRET et la date d'évaluation, puis écrit et relit deux objets :

- `processed/prospects/history/<horodatage>.parquet` : archive de publication ;
- `processed/prospects/current.parquet` : résultat utilisé par Streamlit.

Le script d'export seul ne relance pas les tests dbt. Le workflow décrit ci-dessous garantit leur exécution préalable. Le fichier current est publié en un seul objet après l'archive ; les utilisateurs ne lisent pas un fichier partiellement envoyé. Les archives s'accumulent dans S3.

Le fichier Parquet contient toutes les colonnes du modèle de scoring, y compris les noms disponibles et les statuts de diffusion. Garder S3 privé et configurer l'accès de l'application selon les destinataires prévus.

## 4. Préparer GitHub

Avant tout commit, ajouter ces règles au `.gitignore` EXISTANT (ne pas remplacer les autres règles) :

```gitignore
.env
.env.*
!.env.example
.streamlit/secrets.toml
**/secrets.toml
.venv/
__pycache__/
*.pyc
data/
dbt_prospection/target/
dbt_prospection/logs/
dbt_prospection/.user.yml
```

Vérifier `git status`. Le dépôt doit contenir le code, les modèles dbt, les fichiers de dépendances et `.github/workflows/monthly-data.yml`. Ne pas y ajouter les données, les secrets ni le notebook avec des sorties nominatives sans les avoir examinées. Ajouter un fichier au `.gitignore` ne retire pas un secret déjà suivi par Git.

Le profil `deployment/dbt/profiles.yml` est dédié au runner GitHub : il reçoit le chemin DuckDB via une variable. Ton profil local n'est pas modifié.

Dans le dépôt : Settings → Secrets and variables → Actions → New repository secret. Créer :

- `INSEE_API_KEY`
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`

Utiliser les clés de l'utilisateur IAM dédié au projet, pas celles de l'administrateur. Ses droits existants sur le bucket doivent couvrir la lecture et l'écriture de `raw/` et `processed/`, ainsi que la liste du bucket.

Cette première configuration utilise des secrets GitHub chiffrés pour rester compatible avec les scripts existants. Une migration vers un rôle AWS et OIDC nécessiterait aussi d'adapter ces scripts pour les identifiants temporaires.

## 5. Workflow GitHub Actions fourni

Le workflow est prévu le **5 de chaque mois à 05:17 UTC**, pour le mois précédent. La planification n'est pas une garantie d'exécution à la seconde près.

Il effectue, dans cet ordre :

1. Installation de Python 3.12 et des dépendances du pipeline.
2. Téléchargement des trois COG 2026 déjà stockés dans S3 (nécessaires au script de transfert actuel).
3. Collecte du mois précédent, ou du mois saisi au lancement manuel.
4. Envoi des nouvelles pages et manifestes dans S3.
5. Reconstruction de DuckDB depuis toutes les collectes mensuelles terminées dans S3.
6. Exécution de tous les modèles et tests dbt, avec la date UTC du lancement pour le scoring.
7. Publication du Parquet de résultats uniquement si les étapes précédentes réussissent.

Le runner part sans données locales. Les mois historiques restent dans S3 ; le chargeur les retrouve. Les données 2025–2026 et les trois référentiels doivent donc déjà être dans le bucket avant le premier lancement.

Le workflow doit être sur la branche par défaut pour la planification. Dans Actions → Actualisation mensuelle Sirene → Run workflow, un champ `mois` permet un lancement manuel (AAAA-MM). Vide signifie mois précédent. Rejouer un mois crée une nouvelle collecte ; le chargeur conserve la dernière collecte terminée pour ce mois.

Après un échec, consulter les logs et rejouer le mois concerné. Le contrôle de continuité arrête le chargement si un mois manque. Le système n'effectue pas de rattrapage automatique des mois omis ni de réactualisation de tous les statuts historiques. Les immatriculations publiées tardivement peuvent nécessiter de rejouer les derniers mois.

Aucun lancement distant n'a été réalisé lors de la préparation de cette archive. L'exécution et la programmation ne deviennent effectives qu'après ajout du workflow au dépôt et configuration des secrets.

## 6. Streamlit Community Cloud

Créer une application depuis ton compte lié à GitHub : sélectionner le dépôt, la branche et le fichier **`dashboard/app.py`**. Choisir Python **3.12** dans les paramètres avancés. Le `dashboard/requirements.txt` accompagne l'application.

Dans les Secrets de l'application, renseigner ce TOML avec les valeurs réelles uniquement dans l'interface Streamlit :

```toml
DATA_SOURCE = "s3"
AWS_DEFAULT_REGION = "eu-west-3"
S3_BUCKET_NAME = "prospection-b2b-cmaussang-2026"
S3_SCORES_KEY = "processed/prospects/current.parquet"
AWS_ACCESS_KEY_ID = "CLE_DE_LECTURE"
AWS_SECRET_ACCESS_KEY = "SECRET_DE_LECTURE"
```

Prévoir pour Streamlit un accès IAM séparé limité à `s3:GetObject` sur :

```text
arn:aws:s3:::prospection-b2b-cmaussang-2026/processed/prospects/current.parquet
```

L'application n'a pas besoin d'écrire dans S3 ni d'accéder à la clé Insee. Ne pas copier la clé Insee dans ses secrets.

Configurer la visibilité de l'application pour l'équipe prévue avant de partager son lien. Le bucket reste privé même si l'application est partagée.

Une publication mensuelle sera visible au prochain rechargement après expiration du cache (cinq minutes), ou en cliquant sur « Actualiser les données ». Aucun nouveau déploiement de l'application n'est nécessaire pour mettre à jour les données.

## 7. Vérifications effectuées

- Syntaxe Python et structure du workflow vérifiées.
- Application exécutée avec quatre établissements fictifs couvrant Babies, Newbies, Premiers pas et hors périmètre.
- Indicateurs, filtres prioritaires/hors périmètre et recherche sans résultat vérifiés.
- Export Parquet local exécuté sur une base de test.
- Aucun accès au bucket réel, aucune collecte réelle et aucun déploiement GitHub/Streamlit effectués ici.

Les résultats de démonstration ne sont pas inclus dans l'archive. La première ouverture locale doit lire tes 20 572 établissements réels.
