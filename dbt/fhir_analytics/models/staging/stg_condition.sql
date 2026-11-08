with latest as (
    {{ latest_version(source('raw', 'raw_condition')) }}
)

select
    resource_id as condition_id,
    json_extract_string(resource, '$.patient_token') as patient_token,
    replace(json_extract_string(resource, '$.encounter.reference'), 'Encounter/', '')
        as encounter_id,
    json_extract_string(resource, '$.code.coding[0].code') as condition_code,
    json_extract_string(resource, '$.code.coding[0].display') as condition_display,
    json_extract_string(resource, '$.clinicalStatus.coding[0].code') as clinical_status,
    {{ to_utc_ts("json_extract_string(resource, '$.recordedDate')") }} as recorded_at,
    {{ to_utc_ts('last_updated') }} as last_updated
from latest
