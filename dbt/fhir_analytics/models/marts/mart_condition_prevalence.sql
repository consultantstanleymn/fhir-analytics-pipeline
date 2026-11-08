-- Share of patients with each condition (any clinical status).
with total as (
    select count(*) as total_patients from {{ ref('dim_patient') }}
)

select
    c.condition_code,
    c.condition_display,
    count(distinct c.patient_token) as patients_with_condition,
    t.total_patients,
    round(count(distinct c.patient_token) * 1.0 / t.total_patients, 4) as prevalence
from {{ ref('stg_condition') }} as c
inner join {{ ref('dim_patient') }} as p on c.patient_token = p.patient_token
cross join total as t
group by c.condition_code, c.condition_display, t.total_patients
