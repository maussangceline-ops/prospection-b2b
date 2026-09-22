select
    DEP as code_departement,
    LIBELLE as nom_departement,
    REG as code_region

from {{ source('prospection_raw', 'departements') }}