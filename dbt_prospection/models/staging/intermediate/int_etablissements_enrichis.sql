{{ config(materialized='view') }}

with etablissements as (

    select *
    from {{ ref('stg_sirene_etablissements') }}

),

communes as (

    select *
    from {{ ref('stg_communes') }}

),

departements as (

    select *
    from {{ ref('stg_departements') }}

),

regions as (

    select *
    from {{ ref('stg_regions') }}

)

select
    etablissements.*,

    communes.nom_commune,
    communes.type_commune,
    communes.code_commune_parente,
    communes.code_departement,
    departements.nom_departement,
    communes.code_region,
    regions.nom_region,
    stg_codes_postaux.codes_postaux_commune,
    coalesce(stg_codes_postaux.nombre_codes_postaux, 0) as nombre_codes_postaux_commune,
    stg_codes_postaux.date_recuperation as date_referentiel_postal,
    case
        when etablissements.code_postal is not null then etablissements.code_postal
        when stg_codes_postaux.nombre_codes_postaux = 1 then stg_codes_postaux.code_postal_unique
        when stg_codes_postaux.nombre_codes_postaux > 1 then 'Plusieurs codes possibles'
        when etablissements.code_postal_masque then 'ND'
        else 'NR'
    end as code_postal_affiche,
    case
        when etablissements.code_postal is not null then 'Sirene'
        when stg_codes_postaux.nombre_codes_postaux = 1 then 'Commune (La Poste)'
        when stg_codes_postaux.nombre_codes_postaux > 1 then 'Commune : plusieurs codes'
        else 'Aucune correspondance'
    end as source_code_postal

from etablissements

left join communes
    on etablissements.code_commune = communes.code_commune

left join departements
    on communes.code_departement = departements.code_departement

left join regions
    on communes.code_region = regions.code_region

left join {{ ref('stg_codes_postaux') }} as stg_codes_postaux
    on etablissements.code_commune = stg_codes_postaux.code_commune
