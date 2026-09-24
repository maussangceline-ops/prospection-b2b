{{ config(materialized='view') }}
{% set date_evaluation = var('date_evaluation', run_started_at.strftime('%Y-%m-%d')) %}

with entreprises as (
    select siren, min(date_creation_entreprise) as date_creation_entreprise
    from {{ ref('int_etablissements_enrichis') }}
    group by siren
), evenements_admissibles as (
    select distinct
        stg_evenements_etablissements.siren,
        stg_evenements_etablissements.siret_predecesseur,
        stg_evenements_etablissements.siret_successeur,
        stg_evenements_etablissements.date_evenement
    from {{ ref('stg_evenements_etablissements') }} as stg_evenements_etablissements
    inner join entreprises
        on stg_evenements_etablissements.siren = entreprises.siren
    inner join {{ source('mouvements_raw', 'controles_mouvements') }} as controles_mouvements
        on stg_evenements_etablissements.siren = controles_mouvements.siren
        and stg_evenements_etablissements.collecte_id = controles_mouvements.collecte_id
    where stg_evenements_etablissements.type_evenement = 'transfert_etablissement'
      and stg_evenements_etablissements.qualification = 'confirme_par_lien'
      and controles_mouvements.statut_couverture = 'population_retrouvee'
      and stg_evenements_etablissements.siret_predecesseur is not null
      and stg_evenements_etablissements.siret_successeur is not null
      and stg_evenements_etablissements.siret_predecesseur <> stg_evenements_etablissements.siret_successeur
      and stg_evenements_etablissements.date_evenement > entreprises.date_creation_entreprise
      and stg_evenements_etablissements.date_evenement > cast('{{ date_evaluation }}' as date) - interval '12 months'
      and stg_evenements_etablissements.date_evenement <= cast('{{ date_evaluation }}' as date)
)
select siren,
    count(*) as nombre_transferts_12_mois,
    max(date_evenement) as date_dernier_transfert,
    50 + 25 * (count(*) - 1) as bonus_transferts_potentiel
from evenements_admissibles
group by siren
