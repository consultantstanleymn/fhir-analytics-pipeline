# Key rotation

The pipeline replaces patient ids and record numbers with HMAC-SHA256 tokens. This file explains how the keys have versions and how to rotate them. All data is synthetic.

## Why tokens carry a key id

A token looks like `v1.<64 hex characters>`. The part before the dot is the key id. The id tells you which key made the token.

- A new key gives new tokens. Old tokens stay valid for the old files.
- You can read an old file and know which key made its tokens.
- You can retire a key and find every file that still uses it.

## Where the keys live

| Setting | Meaning |
|---|---|
| `FHIR_HMAC_KEYS` | JSON object of key id to key, for example `{"v1": "...", "v2": "..."}` |
| `FHIR_HMAC_ACTIVE` | The key id that new tokens use |
| `FHIR_HMAC_KEY` | Old single key. If `FHIR_HMAC_KEYS` is not set, this key becomes key id `v1` |

Today the keys come from the environment. The Bicep template has a Key Vault with a secrets-reader role for the pipeline identity. The code does not read Key Vault. That link is authored, not run. Never put a key in code, in a log or in a note.

## Rotation steps

1. Make a new random key. Give it the next id, for example `v2`.
2. Add it to `FHIR_HMAC_KEYS`. Keep the old key in the list.
3. Set `FHIR_HMAC_ACTIVE` to `v2`.
4. Run the pipeline. New raw rows get `v2` tokens.
5. Check the curated files: new files have `v2.` tokens, and old files still have `v1.` tokens.
6. When no one needs the old tokens, remove the old key from the list. Do this only after a plan for the old files (see Revocation).

The test `test_old_curated_parquet_still_readable_after_rotation` builds the marts under `v1`, switches to `v2`, builds again, and checks both sets of files.

## What changes for the user

- Tokens change. The same patient gets an unrelated token under each key. The test `test_tokens_do_not_link_across_versions` checks this.
- Marts that hold no tokens, such as the readmission mart, give the same values when the whole warehouse is built under one key.
- A long-term join across versions needs a controlled re-tokenization job. That job would run inside the trusted zone, where raw ids are known. It is not built. Without it, a patient seen under `v1` and `v2` looks like two patients.
- The raw tables store tokens, not source ids. Rows loaded before a rotation keep their old tokens, and a dbt full refresh does not change them. Only a re-load of the landing blobs into a new warehouse gives one key id for all rows.
- A warehouse that holds rows from two key versions counts a patient seen under both keys as two patients. A readmission that crosses the rotation date is not found. The rotation test builds each version in its own warehouse, so it does not cover this case.

## Revocation

If a key leaks:

1. Set a new active key at once.
2. Remove the leaked key from the list.
3. Rebuild the warehouse from the landing blobs, which hold the source ids, so all tokens use the new key.
4. Replace the curated files that carry tokens from the leaked key.
5. Write the event in the incident log.

Step 3 needs the landing blobs. They stay in the identified zone and need their own access control.

## Limits

- The key id is not secret. It only names the key.
- Rotation does not change data that has already left the system.
- This design shows the pattern. It is not a key management service.
