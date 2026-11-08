select
    cast(date_trunc('week', start_at) as date) as week_start,
    department,
    count(*) as encounters,
    count(*) filter (where is_inpatient) as inpatient_encounters
from {{ ref('fct_encounters') }}
group by 1, 2
