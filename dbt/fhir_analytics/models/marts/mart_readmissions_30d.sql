-- 30-day readmission rate by department, plus one ALL row.
with by_department as (
    select
        department,
        count(*) as index_stays,
        count(*) filter (where readmitted_30d) as readmissions
    from {{ ref('int_index_stays') }}
    group by department
),

combined as (
    select * from by_department
    union all
    select
        'ALL' as department,
        coalesce(sum(index_stays), 0) as index_stays,
        coalesce(sum(readmissions), 0) as readmissions
    from by_department
)

select
    department,
    index_stays,
    readmissions,
    round(readmissions * 1.0 / nullif(index_stays, 0), 4) as readmission_rate
from combined
