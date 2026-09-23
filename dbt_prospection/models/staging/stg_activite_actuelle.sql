{{ config(materialized='view') }}

select
    *,
    case categorie_juridique_actuelle
        when '1000' then 'Entrepreneur individuel'
        when '5498' then 'SARL unipersonnelle'
        when '5499' then 'SARL'
        when '5710' then 'SAS'
        when '5720' then 'SAS unipersonnelle'
        else case when categorie_juridique_actuelle is null then 'NR'
            else 'Autre catégorie — ' || categorie_juridique_actuelle end
    end as libelle_categorie_juridique
from {{ source('activite_raw', 'verifications_activite') }}
