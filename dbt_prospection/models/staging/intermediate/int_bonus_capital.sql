{{ config(materialized='view') }}
{% set date_evaluation = var('date_evaluation', run_started_at.strftime('%Y-%m-%d')) %}
with entreprises as (
    select siren, min(date_creation_entreprise) as date_creation_entreprise
    from {{ ref('int_etablissements_enrichis') }} group by siren
), publications as (
    select distinct siren, date_publication, date_publication_avant,
        capital_avant, capital_apres, devise, variation_observee
    from {{ ref('stg_capital_variations') }}
    where admissible_scoring_publication
      and date_publication <= cast('{{ date_evaluation }}' as date)
), ordre as (
    select *,
        lag(capital_avant) over historique as precedent_avant,
        lag(capital_apres) over historique as precedent_apres,
        lag(devise) over historique as precedente_devise,
        count(*) over (partition by siren, date_publication) as publications_meme_jour
    from publications
    window historique as (partition by siren order by date_publication,
        date_publication_avant, capital_avant, capital_apres, devise)
), retenues as (
    select ordre.* from ordre
    inner join entreprises on ordre.siren = entreprises.siren
    where publications_meme_jour = 1
      and not (capital_avant is not distinct from precedent_avant
               and capital_apres is not distinct from precedent_apres
               and devise is not distinct from precedente_devise)
      and date_publication > cast('{{ date_evaluation }}' as date) - interval '12 months'
      and date_publication > entreprises.date_creation_entreprise
      and date_publication_avant >= entreprises.date_creation_entreprise
), comptage as (
    select siren,
        count(*) filter (where variation_observee = 'hausse') as nombre_hausses_capital_12_mois,
        count(*) filter (where variation_observee = 'baisse') as nombre_baisses_capital_12_mois,
        max(date_publication) as date_derniere_publication_capital
    from retenues group by siren
)
select *,
    case when nombre_hausses_capital_12_mois = 0 then 0
         else 50 + 25 * (nombre_hausses_capital_12_mois - 1) end
    - 25 * nombre_baisses_capital_12_mois as bonus_capital_potentiel
from comptage
