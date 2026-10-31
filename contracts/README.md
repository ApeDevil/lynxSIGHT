# Data contracts

Every structure LYNX SIGHT stores or sends between processes is defined once, as Rust types in
[`software/desktop/crates/contracts`](../software/desktop/crates/contracts/src/lib.rs). The files
here and the UI's TypeScript types are generated from them; never edit them by hand.

| Contract | Version | Generated file |
|---|---|---|
| Engine protocol (core ⇄ `sight-engine`), requests | `ENGINE_PROTOCOL_VERSION` = 1 | [`engine-request.v1.schema.json`](schemas/engine-request.v1.schema.json) |
| Engine protocol, responses | same | [`engine-response.v1.schema.json`](schemas/engine-response.v1.schema.json) |
| Calibration profile (stored) | `PROFILE_SCHEMA_VERSION` = 1 | [`profile.v1.schema.json`](schemas/profile.v1.schema.json) |
| Display layout | with the profile | [`display-layout.v1.schema.json`](schemas/display-layout.v1.schema.json) |
| Pointer intent | 1 | [`pointer-intent.v1.schema.json`](schemas/pointer-intent.v1.schema.json) |

Regenerate after changing a contract type, from `software/desktop/`:

```bash
UPDATE_CONTRACTS=1 cargo test -p lynx-sight-contracts   # JSON Schemas here + TS in app/src/lib/contracts
```

Without `UPDATE_CONTRACTS` the same test fails when a schema is stale. The Python engine's tests
(`software/diagnostic/tests/test_engine_contract.py`) validate every message it produces against
these schemas, so both sides agree on the wire.

## Rules for changing a contract

* Adding an optional field is compatible; anything else (renaming, removing, changing a type or
  meaning) bumps the version.
* Engine protocol: both sides must speak the same version; `hello` refuses others. Bump
  `ENGINE_PROTOCOL_VERSION` and `PROTOCOL_VERSION` in `lynx_sight_diag/engine/protocol.py`
  together, and rename the schema files.
* Profile: bump `PROFILE_SCHEMA_VERSION` and add a migration step from the previous version in
  `lynx-sight-profile` (`migrate.rs`) with a fixture of the old version under
  `software/desktop/crates/profile/tests/fixtures/`. Profiles newer than the software are refused,
  never rewritten.
* Gaze-model `parameters` belong to the engine (`kind` + `kind_version`); the core stores them
  without interpreting them.
