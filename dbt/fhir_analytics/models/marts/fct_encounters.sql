{{
    config(
        materialized='incremental',
        unique_key='encounter_id',
        incremental_strategy='delete+insert'
    )
}}

-- Incremental on meta.lastUpdated: only encounters newer than the newest one already
-- in this table are processed. delete+insert replaces changed rows by encounter_id.
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
    current_timestamp as dbt_loaded_at
from {{ ref('int_encounters_enriched') }} as e
inner join {{ ref('dim_department') }} as d on e.department = d.department_name
{% if is_incremental() %}
where e.last_updated > (select max(last_updated) from {{ this }})
{% endif %}
