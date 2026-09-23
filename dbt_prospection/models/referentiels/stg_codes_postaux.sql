{{ config(materialized='view') }}

select
    code_commune,
    count(distinct code_postal) as nombre_codes_postaux,
    string_agg(distinct code_postal, ', ' order by code_postal) as codes_postaux_commune,
    case when count(distinct code_postal) = 1 then min(code_postal) end as code_postal_unique,
    max(date_recuperation) as date_recuperation
from {{ source('postal_raw', 'codes_postaux') }}
group by code_commune
