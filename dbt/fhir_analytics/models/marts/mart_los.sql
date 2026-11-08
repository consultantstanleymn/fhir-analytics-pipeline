-- Length of stay in days for finished inpatient stays, by department.
select
    department,
    count(*) as stays,
    round(avg(los_days), 2) as avg_los_days,
    quantile_cont(los_days, 0.5) as median_los_days,
    quantile_cont(los_days, 0.9) as p90_los_days
from {{ ref('fct_encounters') }}
where is_inpatient and is_finished
group by department
