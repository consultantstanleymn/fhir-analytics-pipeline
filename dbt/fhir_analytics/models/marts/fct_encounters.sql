{{
    config(
        materialized='incremental',
        unique_key='encounter_id',
        incremental_strategy='delete+insert',
        on_schema_change='fail'
    )
}}

-- Incremental on the raw load time (_loaded_at), not on meta.lastUpdated.
-- A row that arrives late, with a lastUpdated older than the newest one in this table, is still
-- picked up, because its load time is newer than the last run. delete+insert replaces changed
-- rows by encounter_id, so a re-run on the same data changes nothing.
select
    e.encounter_id,
    e.patient_token,
    d.department_id,
    e.department,
    e.status,
    e.class_code,
    e.is_inpatient,
    e.is_finished,
    e.is_expired,
    e.start_at,
    e.end_at,
    e.los_days,
    e.last_updated,
    e.loaded_at as source_loaded_at,
    current_timestamp as dbt_loaded_at
from {{ ref('int_encounters_enriched') }} as e
inner join {{ ref('dim_department') }} as d on e.department = d.department_name
{% if is_incremental() %}
    where e.loaded_at > (select max(source_loaded_at) from {{ this }})
{% endif %}
