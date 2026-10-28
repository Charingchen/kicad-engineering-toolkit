# Read-only Python core (first slice)

Implemented: `kicad_toolkit.project.validate` and `kicad_toolkit.build.plan`.
Run from a clean repository checkout using Python 3.10+ (tested on 3.12.14).
Only the Python standard library is required; no installation, KiCad, network,
agent service, or supplier account is needed.

```sh
python -m unittest discover -s tests -v
```

```python
from kicad_toolkit import project, build

workspace = "tests/fixtures/materials"
validation = project.validate(workspace)
assert validation["valid"], validation["errors"]
result = build.plan(workspace, 2, spare_targets={"controller": 1})
print(result)
```

The fixture is synthetic. It contains no validated hardware design. Its two
additional builds can be assembled from free stock; the controller spare target
is short by one today. Incoming controllers reduce additional purchasing to zero.

## API and diagnostics

`project.validate(path)` reads the six JSON/CSV record files and returns `valid`,
`workspace_revision`, `input_records`, `errors`, `warnings`, and `unknowns`.
Errors contain a stable `code`, the relevant `record` (filename or event ID), and
`message`. Missing files, malformed data, unsupported schemas, invalid counts,
unknown references, duplicate identities, inconsistent orders, and invalid ledger
balances fail validation. Unknown counts and an unset active BOM are reported
separately; a blank starter template is valid but cannot be planned yet.

`build.plan(path, build_count, *, bom_revision=None, spare_targets=None)` reloads
and validates records. Invalid records raise `project.InvalidWorkspace` with its
structured `report`; invalid requests raise `ValueError`. A positive Python
integer is required for the count (booleans are rejected). The request means
additional, unreserved builds; callers must resolve any overlap with existing
build IDs before requesting this operation.

An omitted BOM revision selects the active revision. Repeated part IDs on distinct
BOM lines are summed. Omitted spare targets use the workspace targets; an explicit
mapping replaces them completely (`{}` means no spares). Targets are workspace
counts, including parts absent from the selected BOM, not counts per build.

Each line reports `physical`, `reserved`, `free`, `incoming`, `demand`,
`spare_target`, `shortage_now`, and `additional_to_order`. Unknown physical/free
stock and both shortages remain `None`; recorded reservations remain explicit.
`can_assemble_now` checks free stock against new build demand.
`spare_targets_met_now` checks demand plus spares. Incoming orders never establish
readiness today. Plans include revision, inputs, assumptions, warnings and unknowns.

## Draft contract choices enforced here

- Headers match the starter CSVs exactly. IDs are case-sensitive. Quantities are
  discrete integer counts; BOM, order and event quantities are positive,
  cancellations and spare targets may be zero.
- `stock_counts_verified` is an explicit assertion that the ledger accounts for
  all usable stock at all locations for that part. Events alone never verify a
  count. A listed part with no events has verified zero stock; an unlisted part
  remains unknown, even with receipts. Nonzero initial counts require evidenced
  `adjustment_in` events. The core cannot independently verify a physical count.
- Replay existing ledger rows **in CSV order**, not timestamp order. Each prefix
  must have nonnegative physical, reserved and free balances at each location.
  Release/consumption must fit the same part/location/build reservation.
  Adjustments require a reason; all events require an evidence source and a
  timezone-bearing timestamp. Operation IDs may repeat across related rows;
  event IDs may not repeat.
- Builds referenced by allocations must exist in `builds.json`, with a unique
  `build_id`, an existing `bom_revision`, and a recognized `status`.
- For an ordered receipt, `order_id` identifies the order and `source` is exactly
  its `line_id` (not a URL or an invented compound identifier). Evidence for that
  line is in `orders.csv.source`. Receipts without an order ID may use a direct
  evidence reference. Parts must match; receipts plus cancellations cannot exceed
  ordered quantity. Dates never generate receipts.
- `planned` orders have no receipts/cancellations and contribute no incoming stock.
  `ordered` has no receipts and a positive remainder; `partially_received` has
  receipts and a positive remainder. `received` has receipts and no remainder;
  `cancelled` has cancellations and no remainder. Partial cancellations may coexist
  with receipts; no unreceived, uncancelled quantity is silently discarded.

## Limits and next work

These operations open records for reading only. No inventory writer, operation
replay endpoint, expected-revision check, locking, atomic transaction, crash
recovery, or consistent snapshot under concurrent manual edits is implemented.
Run against a quiescent workspace. Plans identify the recorded revision; they do
not guarantee that records stay at that revision afterward.

Validation covers the materials semantics above. Requirements, engineering
claims, decisions, actual usage, substitutions, historical immutability, and test
evidence are not validated. Move-pair integrity is also deferred. A part's
`hardware_tested` label is not proof that a design works. The core does not infer
passed tests, variants, pin assignments or substitutions. No CLI, MCP, resume,
BOM writer, purchasing, or CAD integration is provided. Implement transaction
safety and build-history invariants before expanding to those operations.
