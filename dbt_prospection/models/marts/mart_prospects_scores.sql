{{ config(materialized='table') }}

{% set date_evaluation = var(
    'date_evaluation',
    run_started_at.strftime('%Y-%m-%d')
) %}

with entreprises as (

    select
        int_etablissements_enrichis.*,
        stg_activite_actuelle.date_verification,
        stg_activite_actuelle.statut_etablissement_actuel,
        stg_activite_actuelle.statut_entreprise_actuel,
        stg_activite_actuelle.categorie_juridique_actuelle,
        stg_activite_actuelle.libelle_categorie_juridique,
        coalesce(stg_activite_actuelle.etat_activite, 'À vérifier') as etat_activite,
        coalesce(stg_activite_actuelle.etat_activite = 'Actif', false)
            as activite_confirmee,
        stg_bodacc_controles.date_verification_bodacc,
        coalesce(stg_bodacc_controles.statut_bodacc, 'À vérifier') as statut_bodacc,
        coalesce(stg_bodacc_controles.motif_bodacc, 'Contrôle BODACC absent') as motif_bodacc,
        stg_bodacc_controles.nombre_annonces_bodacc,
        stg_bodacc_controles.date_jugement_bodacc,
        stg_bodacc_controles.nature_jugement_bodacc,
        stg_bodacc_controles.url_annonce_bodacc,
        coalesce(stg_activite_actuelle.etat_activite = 'Actif'
            and stg_bodacc_controles.statut_bodacc = 'Aucune procédure repérée', false)
            as admissible_prospection,
        cast('{{ date_evaluation }}' as date) as date_evaluation,
        'v1.2' as version_score,
        coalesce(int_bonus_transferts.nombre_transferts_12_mois, 0) as nombre_transferts_12_mois,
        int_bonus_transferts.date_dernier_transfert,
        coalesce(int_bonus_transferts.bonus_transferts_potentiel, 0) as bonus_transferts_potentiel,
        coalesce(int_bonus_capital.nombre_hausses_capital_12_mois, 0) as nombre_hausses_capital_12_mois,
        coalesce(int_bonus_capital.nombre_baisses_capital_12_mois, 0) as nombre_baisses_capital_12_mois,
        coalesce(int_bonus_capital.bonus_capital_potentiel, 0) as bonus_capital_potentiel,
        int_bonus_capital.date_derniere_publication_capital,
        'publication_bodacc' as reference_date_capital

    from {{ ref('int_etablissements_enrichis') }} as int_etablissements_enrichis
    left join {{ ref('stg_activite_actuelle') }} as stg_activite_actuelle
        on int_etablissements_enrichis.siret = stg_activite_actuelle.siret
    left join {{ ref('stg_bodacc_controles') }} as stg_bodacc_controles
        on int_etablissements_enrichis.siren = stg_bodacc_controles.siren

    left join {{ ref('int_bonus_transferts') }} as int_bonus_transferts
        on int_etablissements_enrichis.siren = int_bonus_transferts.siren

    left join {{ ref('int_bonus_capital') }} as int_bonus_capital
        on int_etablissements_enrichis.siren = int_bonus_capital.siren

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
        end as bonus_naf,
        case when segment_anciennete in ('date_invalide', 'hors_perimetre_v1')
            then null else bonus_transferts_potentiel end as bonus_transferts,
        case when segment_anciennete in ('date_invalide', 'hors_perimetre_v1')
            then null else bonus_capital_potentiel end as bonus_capital

    from segmentation

),

total as (

    select
        *,
        score_anciennete + bonus_naf + bonus_transferts + bonus_capital as score_total

    from composantes

)

select
    *,
    case when date_derniere_publication_capital is not null
        then 'Variation de capital publiée le ' || strftime(date_derniere_publication_capital, '%d/%m/%Y')
        else null end as libelle_publication_capital,

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
        when bonus_capital > 0 and bonus_transferts = 0
            then 'Présenter clairement vos services et vos projets à de nouveaux clients.'
        when bonus_transferts > 0
            then 'Accompagner votre changement d’implantation avec des supports présentant clairement vos services.'
        when segment_anciennete = 'lancement'
            then 'Clarifier votre offre pour convaincre vos premiers clients.'
        when segment_anciennete = 'developpement'
            then 'Phase intermédiaire : présenter le produit et rappeler à partir du 10e mois en activite.'
        when segment_anciennete = 'renouvellement_prospection'
            then 'Bilan des succès année 1 pour structure votre offre et toucher de nouveaux clients.'
        else null
    end as angle_commercial

from total
