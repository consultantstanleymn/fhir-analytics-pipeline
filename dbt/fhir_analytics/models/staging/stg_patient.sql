with latest as (
    {{ latest_version(source('raw', 'raw_patient')) }}
)

select
    resource_id as patient_token,
    json_extract_string(resource, '$.mrn_token') as mrn_token,
    json_extract_string(resource, '$.gender') as gender,
    cast(json_extract_string(resource, '$.birth_year') as integer) as birth_year,
    json_extract_string(resource, '$.state') as state,
    {{ to_utc_ts('last_updated') }} as last_updated
from latest
