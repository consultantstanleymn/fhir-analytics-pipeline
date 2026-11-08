-- Index stays for the 30-day readmission metric.
-- Index stay: inpatient, finished, patient did not die. Readmitted: the same patient has
-- another inpatient stay that starts at or after the discharge and within 30 calendar days.
with inpatient as (
    select
        encounter_id,
        patient_token,
        department,
        start_at,
        end_at,
        is_finished,
        is_expired
    from {{ ref('fct_encounters') }}
    where is_inpatient
)

select
    i.encounter_id,
    i.patient_token,
    i.department,
    cast(i.end_at as date) as discharge_date,
    exists(
        select 1
        from inpatient as n
        where
            n.patient_token = i.patient_token
            and n.encounter_id <> i.encounter_id
            and n.start_at >= i.end_at
            and date_diff('day', cast(i.end_at as date), cast(n.start_at as date)) <= 30
    ) as readmitted_30d
from inpatient as i
where i.is_finished and not i.is_expired
