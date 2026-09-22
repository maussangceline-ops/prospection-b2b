with controles as (

    select
        *,

        case
            when date_evaluation
                >= date_creation_entreprise + interval '12 months'
                then null

            when date_evaluation
                < date_creation_entreprise + interval '3 months'
                or date_evaluation
                >= date_creation_entreprise + interval '9 months'
                then 100

            else 50
        end as anciennete_attendue,

        case
            when date_evaluation
                >= date_creation_entreprise + interval '12 months'
                then null
            when naf_etablissement = '58.29C' then 30
            when naf_etablissement = '62.02A' then 20
            when naf_etablissement = '62.01Z' then 10
        end as bonus_attendu

    from {{ ref('mart_prospects_scores') }}

)

select *

from controles

where date_creation_entreprise is null
   or anciennete_jours < 0

   or score_anciennete is distinct from anciennete_attendue

   or bonus_naf is distinct from bonus_attendu

   or score_total is distinct from (
       anciennete_attendue + bonus_attendu
   )

   or couleur_priorite is distinct from (
       case
           when anciennete_attendue is null then null
           when anciennete_attendue + bonus_attendu >= 81 then 'vert'
           else 'orange'
       end
   )