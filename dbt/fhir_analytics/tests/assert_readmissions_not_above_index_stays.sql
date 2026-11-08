-- Singular test: readmissions can never exceed index stays, and the ALL row is the sum.
select department
from {{ ref('mart_readmissions_30d') }}
where readmissions > index_stays
union all
select 'ALL' as department
from {{ ref('mart_readmissions_30d') }} as a
where
    a.department = 'ALL'
    and a.index_stays <> (
        select sum(index_stays)
        from {{ ref('mart_readmissions_30d') }}
        where department <> 'ALL'
    )
