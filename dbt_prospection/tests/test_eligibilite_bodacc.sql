-- Un contrôle manquant n'est jamais interprété comme une absence de procédure.
select siret
from {{ ref('mart_prospects_scores') }}
where admissible_prospection is distinct from
    coalesce(activite_confirmee and statut_bodacc = 'Aucune procédure repérée', false)
   or date_verification_bodacc is null
   or date_verification_bodacc > current_date
   or (statut_bodacc like 'Exclusion%' and url_annonce_bodacc is null)
union all
select 'controle_manquant'
where (select count(*) from {{ ref('stg_bodacc_controles') }}) <>
      (select count(distinct siren) from {{ ref('int_etablissements_enrichis') }})
