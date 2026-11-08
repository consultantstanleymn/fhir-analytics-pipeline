select distinct
    md5(department) as department_id,
    department as department_name
from {{ ref('stg_encounter') }}
