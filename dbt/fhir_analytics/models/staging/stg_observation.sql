with latest as (
    {{ latest_version(source('raw', 'raw_observation')) }}
)

select
    resource_id as observation_id,
    json_extract_string(resource, '$.patient_token') as patient_token,
    replace(json_extract_string(resource, '$.encounter.reference'), 'Encounter/', '')
        as encounter_id,
    json_extract_string(resource, '$.code.coding[0].code') as loinc_code,
    json_extract_string(resource, '$.code.coding[0].display') as observation_display,
    try_cast(json_extract_string(resource, '$.valueQuantity.value') as double) as value_number,
    json_extract_string(resource, '$.valueQuantity.unit') as value_unit,
    {{ to_utc_ts("json_extract_string(resource, '$.effectiveDateTime')") }} as effective_at,
    {{ to_utc_ts('last_updated') }} as last_updated
from latest
