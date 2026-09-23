-- Ajout ND DR selon le choix des entreprises Non déterminé ou Non renseigné + codes postaux 
select siret
from {{ ref('int_etablissements_enrichis') }}
where
    (disponibilite_nom in ('ND', 'NR') and nom_affiche != disponibilite_nom)
    or (code_postal is not null and (
        code_postal_affiche != code_postal or source_code_postal != 'Sirene'
    ))
    or (code_postal is null and nombre_codes_postaux_commune = 1
        and source_code_postal != 'Commune (La Poste)')
    or (code_postal is null and nombre_codes_postaux_commune > 1
        and (code_postal_affiche != 'Plusieurs codes possibles'
             or source_code_postal != 'Commune : plusieurs codes'))
