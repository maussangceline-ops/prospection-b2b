with etablissements_bruts as (

    select
        mois_collecte,
        collecte_id,
        date_reference,
        siret,
        fichier_source,
        donnees

    from {{ source('prospection_raw', 'sirene_etablissements') }}

),

-- Une ligne par période connue de chaque établissement.
periodes_depliees as (

    select
        siret,
        date_reference,
        unnest(
            json_extract(donnees, '$.periodesEtablissement[*]')
        ) as periode

    from etablissements_bruts

),

periodes_typees as (

    select
        siret,
        date_reference,
        cast(
            json_extract_string(periode, '$.dateDebut')
            as date
        ) as date_debut_periode,
        cast(
            json_extract_string(periode, '$.dateFin')
            as date
        ) as date_fin_periode,
        json_extract_string(
            periode, '$.activitePrincipaleEtablissement'
        ) as naf_etablissement,
        json_extract_string(
            periode, '$.etatAdministratifEtablissement'
        ) as statut_etablissement,
        coalesce(nullif(nullif(trim(json_extract_string(periode, '$.denominationUsuelleEtablissement')), '[ND]'), ''),
            nullif(nullif(trim(json_extract_string(periode, '$.enseigne1Etablissement')), '[ND]'), ''),
            nullif(nullif(trim(json_extract_string(periode, '$.enseigne2Etablissement')), '[ND]'), ''),
            nullif(nullif(trim(json_extract_string(periode, '$.enseigne3Etablissement')), '[ND]'), '')) as nom_etablissement_public

    from periodes_depliees

),

-- Une période est applicable si elle couvre la date de référence.
periodes_applicables as (

    select
        *,
        count(*) over (
            partition by siret
        ) as nombre_periodes_applicables

    from periodes_typees

    where date_debut_periode <= date_reference
      and (
          date_fin_periode is null
          or date_fin_periode >= date_reference
      )

),

champs_extraits as (

    select
        mois_collecte,
        collecte_id,
        date_reference,
        siret,
        fichier_source,

        json_extract_string(donnees, '$.siren') as siren,

        coalesce(
            nullif(nullif(trim(
                json_extract_string(
                    donnees, '$.uniteLegale.denominationUniteLegale'
                )
            ), '[ND]'), ''),

            nullif(nullif(trim(
                json_extract_string(
                    donnees, '$.uniteLegale.denominationUsuelle1UniteLegale'
                )
            ), '[ND]'), '')
,
            nullif(nullif(trim(json_extract_string(donnees, '$.uniteLegale.denominationUsuelle2UniteLegale')), '[ND]'), ''),
            nullif(nullif(trim(json_extract_string(donnees, '$.uniteLegale.denominationUsuelle3UniteLegale')), '[ND]'), '')
        ) as nom_societe,

        json_extract_string(donnees, '$.uniteLegale.categorieJuridiqueUniteLegale') as categorie_juridique,
        json_extract_string(donnees, '$.uniteLegale.nomUniteLegale') as nom_personne_brut,
        json_extract_string(donnees, '$.uniteLegale.nomUsageUniteLegale') as nom_usage_brut,
        json_extract_string(donnees, '$.uniteLegale.prenomUsuelUniteLegale') as prenom_brut,
        json_extract_string(donnees, '$.uniteLegale.denominationUniteLegale') as denomination_brute,

        cast(
            json_extract_string(donnees, '$.etablissementSiege')
            as boolean
        ) as siege,

        cast(
            json_extract_string(
                donnees, '$.uniteLegale.dateCreationUniteLegale'
            ) as date
        ) as date_creation_entreprise,

        json_extract_string(
            donnees, '$.uniteLegale.etatAdministratifUniteLegale'
        ) as statut_entreprise,

        json_extract_string(
            donnees, '$.statutDiffusionEtablissement'
        ) as diffusion_etablissement,

        json_extract_string(
            donnees, '$.uniteLegale.statutDiffusionUniteLegale'
        ) as diffusion_entreprise,

        json_extract_string(
            donnees, '$.adresseEtablissement.codeCommuneEtablissement'
        ) as code_commune,

        json_extract_string(
            donnees, '$.adresseEtablissement.codePostalEtablissement'
        ) as code_postal_brut,

        json_extract_string(
            donnees, '$.trancheEffectifsEtablissement'
        ) as tranche_effectifs,

        json_extract_string(
            donnees, '$.anneeEffectifsEtablissement'
        ) as annee_effectifs

    from etablissements_bruts

),

base as (
select
    champs_extraits.mois_collecte,
    champs_extraits.collecte_id,
    champs_extraits.date_reference,
    champs_extraits.siret,
    champs_extraits.siren,
    champs_extraits.nom_societe,
    champs_extraits.categorie_juridique,
    champs_extraits.nom_personne_brut,
    champs_extraits.nom_usage_brut,
    champs_extraits.prenom_brut,
    champs_extraits.denomination_brute,
    periodes_applicables.nom_etablissement_public,
    champs_extraits.siege,
    champs_extraits.date_creation_entreprise,

    periodes_applicables.date_debut_periode,
    periodes_applicables.date_fin_periode,
    periodes_applicables.naf_etablissement,
    periodes_applicables.statut_etablissement,

    coalesce(
        periodes_applicables.nombre_periodes_applicables, 0
    ) as nombre_periodes_applicables,

    champs_extraits.statut_entreprise,
    champs_extraits.diffusion_etablissement,
    champs_extraits.diffusion_entreprise,
    champs_extraits.code_commune,

    nullif(
        nullif(trim(champs_extraits.code_postal_brut), '[ND]'),
        ''
    ) as code_postal,

    coalesce(
        trim(champs_extraits.code_postal_brut) = '[ND]', false
    ) as code_postal_masque,

    champs_extraits.tranche_effectifs,
    champs_extraits.annee_effectifs,
    champs_extraits.fichier_source

from champs_extraits

left join periodes_applicables
    on champs_extraits.siret = periodes_applicables.siret
),
identites as (
    select *,
        coalesce(
            nom_personne_brut = '[ND]' or nom_usage_brut = '[ND]'
            or prenom_brut = '[ND]' or denomination_brute = '[ND]', false
        ) or coalesce(
            diffusion_entreprise = 'P'
            and (categorie_juridique = '1000' or categorie_juridique like '2%'), false
        ) as identite_masquee,
        coalesce(
            nom_societe,
            nom_etablissement_public,
            case when categorie_juridique = '1000' then
                nullif(trim(concat_ws(' ',
                    nullif(nullif(trim(prenom_brut), '[ND]'), ''),
                    coalesce(nullif(nullif(trim(nom_usage_brut), '[ND]'), ''),
                             nullif(nullif(trim(nom_personne_brut), '[ND]'), ''))
                )), '')
            end
        ) as nom_disponible
    from base
)
select
    * exclude (nom_personne_brut, nom_usage_brut, prenom_brut,
               denomination_brute, nom_etablissement_public,
               identite_masquee, nom_disponible),
    case when identite_masquee then 'ND'
         when nom_disponible is not null then nom_disponible
         else 'NR' end as nom_affiche,
    case when identite_masquee then 'ND'
         when nom_disponible is not null then 'Disponible'
         else 'NR' end as disponibilite_nom
from identites
