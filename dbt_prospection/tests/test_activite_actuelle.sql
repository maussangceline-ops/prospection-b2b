-- Conserver toutes les lignes et vérifier la logique d'activité indépendamment du score.
with anomalies as (
    select siret from {{ ref('mart_prospects_scores') }}
    where activite_confirmee is distinct from (etat_activite = 'Actif')
       or (etat_activite = 'Actif' and (
           statut_etablissement_actuel is distinct from 'A'
           or statut_entreprise_actuel is distinct from 'A'))
       or ((statut_etablissement_actuel = 'F' or statut_entreprise_actuel = 'C')
           and etat_activite <> 'Inactif')
       or date_verification is null
       or date_verification > current_date
)
select siret from anomalies
union all
select 'volume_incorrect'
where (select count(*) from {{ ref('mart_prospects_scores') }})
   <> (select count(*) from {{ ref('int_etablissements_enrichis') }})
