-- One row per encounter (latest version), with derived flags and patient attributes.
select
    e.encounter_id,
    e.patient_token,
    e.status,
    e.class_code,
    e.class_code = 'IMP' as is_inpatient,
    e.department,
    e.start_at,
    e.end_at,
    e.end_at is not null and e.status = 'finished' as is_finished,
    coalesce(e.discharge_disposition = 'exp', false) as is_expired,
    case
        when e.end_at is not null
            then date_diff('day', cast(e.start_at as date), cast(e.end_at as date))
    end as los_days,
    p.gender as patient_gender,
    p.birth_year as patient_birth_year,
    e.last_updated,
    e.loaded_at
from {{ ref('stg_encounter') }} as e
inner join {{ ref('stg_patient') }} as p on e.patient_token = p.patient_token
