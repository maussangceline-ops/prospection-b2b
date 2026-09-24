-- Remplace le contrôle de l'ancien barème, devenu incomplet.
select * from {{ ref('mart_prospects_scores') }}
where version_score is distinct from 'v1.1'
   or nombre_transferts_12_mois < 0
   or bonus_transferts_potentiel is distinct from
       case when nombre_transferts_12_mois = 0 then 0
            else 50 + 25 * (nombre_transferts_12_mois - 1) end
   or (segment_anciennete = 'hors_perimetre_v1' and
       (score_total is not null or couleur_priorite is not null
        or score_anciennete is not null or bonus_naf is not null or bonus_transferts is not null))
   or (segment_anciennete in ('lancement', 'developpement', 'renouvellement_prospection') and (
       score_anciennete is distinct from case when segment_anciennete = 'developpement' then 50 else 100 end
       or bonus_naf is distinct from case naf_etablissement when '58.29C' then 30 when '62.02A' then 20 when '62.01Z' then 10 end
       or bonus_transferts is distinct from bonus_transferts_potentiel
       or score_total is distinct from score_anciennete + bonus_naf + bonus_transferts
       or couleur_priorite is distinct from case when score_total >= 81 then 'vert' else 'orange' end
   ))
   or segment_anciennete = 'date_invalide'
