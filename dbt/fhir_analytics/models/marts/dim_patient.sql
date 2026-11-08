-- Pseudonymized patient dimension. No name, address or exact birth date.
select
    patient_token,
    mrn_token,
    gender,
    birth_year,
    (birth_year / 10) * 10 as birth_decade,
    state
from {{ ref('stg_patient') }}
