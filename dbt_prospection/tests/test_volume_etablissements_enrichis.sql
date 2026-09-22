with volume_source as (

    select count(*) as nombre_lignes
    from {{ ref('stg_sirene_etablissements') }}

),

volume_enrichi as (

    select count(*) as nombre_lignes
    from {{ ref('int_etablissements_enrichis') }}

)

select
    volume_source.nombre_lignes as lignes_avant_jointures,
    volume_enrichi.nombre_lignes as lignes_apres_jointures

from volume_source
cross join volume_enrichi

where volume_source.nombre_lignes <> volume_enrichi.nombre_lignes