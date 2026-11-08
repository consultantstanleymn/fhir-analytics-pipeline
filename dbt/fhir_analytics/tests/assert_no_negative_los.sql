-- Singular test: a stay can not end before it starts.
select
    encounter_id,
    los_days
from {{ ref('fct_encounters') }}
where los_days < 0
