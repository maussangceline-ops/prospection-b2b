select
    REG as code_region,
    LIBELLE as nom_region

from {{ source('prospection_raw', 'regions') }}