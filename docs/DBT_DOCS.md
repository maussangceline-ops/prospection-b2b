# Générer et consulter dbt Docs

Le projet utilise dbt Core 1.x. dbt Docs rassemble les descriptions YAML, les tests définis, les colonnes du catalogue et les dépendances `source()` / `ref()`.

## Prérequis

- Activer l’environnement Python du projet et se placer à la racine `prospection-b2b`.
- Disposer de la base DuckDB déjà chargée, avec les modèles construits.
- Fermer les connexions DuckDB du notebook et arrêter Streamlit local si un verrou empêche l’accès.
- Le profil `dbt_prospection/profiles.yml` doit pointer vers cette base.

Aucune clé R2 n’est nécessaire pour lire le catalogue d’une base locale déjà complète.

## Génération

Utiliser la même date d’évaluation que lors du dernier build. L’exemple suivant correspond à l’actualisation finale du 1er octobre : avant cette actualisation, remplacer cette date par celle du dernier build réussi.

```bash
dbt docs generate --project-dir dbt_prospection --profiles-dir dbt_prospection --vars '{"date_evaluation":"2026-10-01"}'
```

Cette commande compile le projet et interroge le catalogue. Elle ne reconstruit pas les modèles, ne lance pas les tests et ne déclenche aucune collecte. Les métadonnées décrivent les relations existantes ; si elles sont absentes, construire d’abord le projet avec `dbt build`.

## Consultation locale

```bash
dbt docs serve --project-dir dbt_prospection --profiles-dir dbt_prospection --port 8080
```

Ouvrir `http://localhost:8080`. Arrêter le serveur avec `Ctrl+C`.

La documentation permet de consulter :

- la page d’accueil métier du projet ;
- les sources et modèles ;
- les descriptions de colonnes déjà renseignées dans les YAML ;
- les tests déclarés et le graphe des dépendances ;
- l’exposition `dashboard_prospection`, reliée au mart de scores.

Les tests affichés sont des définitions : ce site ne remplace pas le compte rendu d’une exécution `dbt build` ou `dbt test`.

## Fichiers à conserver dans Git

Conserver les `.sql`, `.yml`, la page `dbt_prospection/models/documentation/overview.md`, ce guide et le README. Le dossier généré `dbt_prospection/target/` est déjà ignoré par le dépôt : ne pas le forcer dans Git.

Pour un export HTML autonome sous dbt Core 1.x, vérifier l’option proposée par la version installée avec `dbt docs generate --help`. Si `--static` est disponible :

```bash
dbt docs generate --static --project-dir dbt_prospection --profiles-dir dbt_prospection --vars '{"date_evaluation":"2026-10-01"}'
```

Le fichier attendu est `dbt_prospection/target/static_index.html`. Contrôler son contenu avant partage : il embarque les métadonnées et le SQL du projet. Aucune publication publique automatique n’est ajoutée par ce paquet.

## Ce que le graphe couvre

L’exposition matérialise la dépendance du dashboard envers le mart. L’export Parquet et la lecture R2 ne sont pas des modèles dbt ; ils sont décrits dans l’exposition. Neon est indépendant de dbt et ne doit pas être présenté comme une table transformée par dbt.

Le modèle de score est à la granularité SIRET ; les bonus de mouvements et capital sont agrégés par SIREN, puis joints aux établissements.

Documentation de référence : https://docs.getdbt.com/reference/commands/cmd-docs

Le site officiel peut afficher dbt v2 par défaut : conserver les instructions correspondant à la version Core 1.x utilisée par ce dépôt.
