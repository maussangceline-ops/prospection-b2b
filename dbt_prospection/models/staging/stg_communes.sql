select
    COM as code_commune,
    TYPECOM as type_commune,
    LIBELLE as nom_commune,
    DEP as code_departement,
    REG as code_region,
    nullif(COMPARENT, '') as code_commune_parente

from {{ source('prospection_raw', 'communes') }}

where TYPECOM in ('COM', 'ARM')