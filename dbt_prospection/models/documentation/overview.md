{% docs __overview__ %}
# Le Chant des SIREN

## Finalité

Prioriser les prospects d’une agence qui rend les offres technologiques compréhensibles. Le scoring v1.2 est explicable et fondé sur des règles métier ; il ne prédit pas une probabilité de conversion.

## Organisation des modèles

- **Sources raw** : données administratives SIREN/SIRET, référentiels géographiques et postaux, contrôles d’activité et BODACC, mouvements et capital.
- **Staging** : extraction des champs, typage et préparation des observations.
- **Intermédiaires** : enrichissement des établissements et agrégation des bonus par SIREN.
- **Mart** : `mart_prospects_scores`, une ligne par SIRET, contenant l’admissibilité, les composantes du score et l’angle commercial.
- **Exposition** : `dashboard_prospection`, consommation du mart après export Parquet dans Cloudflare R2.

## Barème

Moins de 3 mois et de 9 à moins de 12 mois : 100 points. De 3 à moins de 9 mois : 50 points. Dès 12 mois, score V1 nul. Les bornes utilisent des mois calendaires.

Bonus NAF : 58.29C = 30, 62.02A = 20, 62.01Z = 10. Transferts admissibles dans les 12 derniers mois : 50 pour le premier, 25 pour chaque suivant. Hausses de capital admissibles : même barème ; chaque baisse admissible retire 25 points.

Vert dès 81 points, orange jusqu’à 80 inclus. Les observations de capital sont datées par leur publication BODACC, et non par une date d’effet juridique présumée.

## Admissibilité et affichage

L’activité confirmée et l’absence de procédure repérée conditionnent l’admissibilité. Le dashboard exclut également les noms ND/NR. Le mart conserve des lignes non admissibles : présence dans le mart et présence dans le listing commercial ne sont pas équivalentes.

La catégorie juridique ne donne pas de points. Les codes postaux possibles d’une commune ne reconstituent pas une adresse exacte. Les ouvertures potentielles non confirmées ne sont pas bonifiées.

## Qualité et traçabilité

Les YAML définissent les tests de présence, unicité, valeurs et relations. Les tests SQL complètent ces contrôles pour le score, les volumes, l’affichage et l’admissibilité. Consulter les résultats du dernier `dbt build` pour connaître leur état d’exécution.

La variable `date_evaluation` doit être explicite pour une exécution reproductible. Les données reflètent les dates de collecte et de vérification ; elles ne sont pas temps réel.

## Stockage et CRM

R2 conserve les archives et les exports. DuckDB héberge les tables et vues transformées. Le CRM de démonstration utilise Neon PostgreSQL, rattaché par SIREN ; les saisies commerciales ne modifient pas le score.

L’architecture Python, R2 et Neon est détaillée dans le README du dépôt. Ce catalogue couvre les dépendances dbt et la consommation du mart par le dashboard.
{% enddocs %}
