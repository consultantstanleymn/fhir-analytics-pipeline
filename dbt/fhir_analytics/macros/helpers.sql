{# FHIR instants are ISO 8601 with a Z. Cast to a UTC timestamp without zone. #}
{% macro to_utc_ts(expr) -%}
    timezone('UTC', cast({{ expr }} as timestamptz))
{%- endmacro %}

{# Keep only the newest version of each resource id. Ties go to the latest load. #}
{% macro latest_version(source_relation) -%}
    select * exclude (rn) from (
        select
            *,
            row_number() over (
                partition by resource_id
                order by last_updated desc, _loaded_at desc, _source_blob desc
            ) as rn
        from {{ source_relation }}
    )
    where rn = 1
{%- endmacro %}
