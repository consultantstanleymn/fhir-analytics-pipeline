with latest as (
    {{ latest_version(source('raw', 'raw_encounter')) }}
)

select
    resource_id as encounter_id,
    json_extract_string(resource, '$.patient_token') as patient_token,
    json_extract_string(resource, '$.status') as status,
    json_extract_string(resource, '$.class.code') as class_code,
    coalesce(
        json_extract_string(resource, '$.serviceType.coding[0].display'), 'Unknown'
    ) as department,
    {{ to_utc_ts("json_extract_string(resource, '$.period.start')") }} as start_at,
    {{ to_utc_ts("json_extract_string(resource, '$.period.end')") }} as end_at,
    json_extract_string(
        resource, '$.hospitalization.dischargeDisposition.coding[0].code'
    ) as discharge_disposition,
    {{ to_utc_ts('last_updated') }} as last_updated
from latest
