{{ config(materialized='view') }}

select * from {{ source('bodacc_raw', 'bodacc_controles') }}
