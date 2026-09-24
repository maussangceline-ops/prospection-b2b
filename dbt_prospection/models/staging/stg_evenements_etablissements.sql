{{ config(materialized='view') }}

{% set date_evaluation = var('date_evaluation', run_started_at.strftime('%Y-%m-%d')) %}

select
    *,
    coalesce(
        date_evenement > cast('{{ date_evaluation }}' as date) - interval '12 months'
        and date_evenement <= cast('{{ date_evaluation }}' as date),
        false
    ) as dans_fenetre_12_mois
from {{ source('mouvements_raw', 'evenements_etablissements') }}
