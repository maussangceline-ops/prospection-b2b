{{ config(materialized='view') }}
-- La date de référence est une publication, pas une date d'effet juridique.
with lecture as (
    select siren, collecte_id, date_collecte,
        json_extract_string(donnees, '$.id_annonce_avant') as id_annonce_avant,
        json_extract_string(donnees, '$.id_annonce_apres') as id_annonce_apres,
        try_cast(json_extract_string(donnees, '$.date_publication_avant') as date) as date_publication_avant,
        try_cast(json_extract_string(donnees, '$.date_publication_apres') as date) as date_publication,
        try_cast(json_extract_string(donnees, '$.capital_avant') as decimal(38,2)) as capital_avant,
        try_cast(json_extract_string(donnees, '$.capital_apres') as decimal(38,2)) as capital_apres,
        json_extract_string(donnees, '$.devise') as devise,
        json_extract_string(donnees, '$.variation_observee') as variation_observee,
        json_extract_string(donnees, '$.descriptif') as descriptif,
        json_extract_string(donnees, '$.url_annonce_avant') as url_annonce_avant,
        json_extract_string(donnees, '$.url_annonce_apres') as url_annonce_apres
    from {{ source('capital_raw', 'capital_variations_a_confirmer') }}
)
select *, coalesce(
    id_annonce_avant is not null and id_annonce_apres is not null
    and id_annonce_avant <> id_annonce_apres
    and date_publication_avant < date_publication
    and date_publication <= date_collecte
    and capital_avant >= 0 and capital_apres >= 0
    and devise is not null and trim(devise) <> ''
    and contains(lower(descriptif), 'capital')
    and not contains(lower(descriptif), 'variable')
    and ((variation_observee = 'hausse' and capital_apres > capital_avant
          and not contains(lower(descriptif), 'diminution')
          and not contains(lower(descriptif), 'réduction')
          and not contains(lower(descriptif), 'reduction'))
      or (variation_observee = 'baisse' and capital_apres < capital_avant
          and not contains(lower(descriptif), 'augmentation'))), false
) as admissible_scoring_publication
from lecture
