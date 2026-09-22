{{ config(materialized='table') }}

{% set date_evaluation = var(
    'date_evaluation',
    run_started_at.strftime('%Y-%m-%d')
) %}

with entreprises as (

    select
        *,
        cast('{{ date_evaluation }}' as date) as date_evaluation,
        'v1' as version_score

    from {{ ref('int_etablissements_enrichis') }}

),

segmentation as (

    select
        *,
        date_evaluation - date_creation_entreprise
            as anciennete_jours,

        case
            when date_creation_entreprise is null
                or date_creation_entreprise > date_evaluation
                then 'date_invalide'

            when date_evaluation
                < date_creation_entreprise + interval '3 months'
                then 'lancement'

            when date_evaluation
                < date_creation_entreprise + interval '9 months'
                then 'developpement'

            when date_evaluation
                < date_creation_entreprise + interval '12 months'
                then 'renouvellement_prospection'

            else 'hors_perimetre_v1'
        end as segment_anciennete

    from entreprises

),

composantes as (

    select
        *,

        case
            when segment_anciennete in (
                'lancement', 'renouvellement_prospection'
            ) then 100
            when segment_anciennete = 'developpement' then 50
            else null
        end as score_anciennete,

        case
            when segment_anciennete in (
                'date_invalide', 'hors_perimetre_v1'
            ) then null
            when naf_etablissement = '58.29C' then 30
            when naf_etablissement = '62.02A' then 20
            when naf_etablissement = '62.01Z' then 10
            else null
        end as bonus_naf

    from segmentation

),

total as (

    select
        *,
        score_anciennete + bonus_naf as score_total

    from composantes

)

select
    *,

    case
        when segment_anciennete = 'lancement'
            then 'Babies'

        when segment_anciennete = 'developpement'
            then 'Newbies'

        when segment_anciennete = 'renouvellement_prospection'
            then 'Premiers pas'

        when segment_anciennete = 'hors_perimetre_v1'
            then concat(
                cast(
                    date_part(
                        'year',
                        age(date_evaluation, date_creation_entreprise)
                    ) as integer
                ),
                case
                    when date_part(
                        'year',
                        age(date_evaluation, date_creation_entreprise)
                    ) = 1 then ' an'
                    else ' ans'
                end
            )

        else null
    end as libelle_age,

    case
        when score_total is null then null
        when score_total >= 81 then 'vert'
        else 'orange'
    end as couleur_priorite,

    case
        when segment_anciennete = 'lancement'
            then 'Clarifier votre offre pour convaincre vos premiers clients.'
        when segment_anciennete = 'developpement'
            then 'Ameliorer vos supports pour developper votre prospection.'
        when segment_anciennete = 'renouvellement_prospection'
            then 'Structurer vos supports pour toucher de nouveaux clients.'
        else null
    end as angle_commercial

from total