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
    regions.nom_region

from etablissements

left join communes
    on etablissements.code_commune = communes.code_commune

left join departements
    on communes.code_departement = departements.code_departement

left join regions
    on communes.code_region = regions.code_region