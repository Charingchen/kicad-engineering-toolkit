# Read-only Python core

Implemented in the first Milestone 1 slice: `project.validate` and `build.plan`.
Python 3.10 or newer is required. Runtime and tests use only the standard library;
no KiCad, network, supplier account, or AI service is needed.

From a clean checkout, run:

```sh
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python - <<'PY'
import json
from kicad_engineering_toolkit import project, build
workspace = 'tests/fixtures/materials-loop'
print(json.dumps(project.validate(workspace), indent=2))
print(json.dumps(build.plan(workspace, build_count=2), indent=2))
PY
```

For use outside the checkout, install with `python -m pip install -e .`.
There is no CLI or MCP server in this slice.

## API and results

`project.validate(workspace)` reads the seven template record files. It returns
`valid`, structured `errors`, `warnings`, and `unknowns`, the declared
`workspace_revision`, an SHA-256 `workspace_fingerprint` covering file names and
contents, `input_records`, `assumptions`, and `supported_checks`. Unknown stock and
an unset active BOM do not invalidate an otherwise empty starter workspace.
Malformed files, unsupported schema versions, references to missing parts/builds,
invalid quantities, duplicate identities, and invalid ledger balances are errors.

`build.plan(workspace, *, build_count, bom_revision=None, spare_targets=None)` first
validates the entire workspace. It returns `ok=False`, errors, and an empty parts
list when validation or request checks fail. It never creates a partial usable
plan from invalid records. The default BOM is the active revision; passing another
existing revision selects it explicitly. Demand aggregates all BOM lines for the
same part. Build count is a nonnegative integer of **additional unreserved builds**;
callers must resolve requests overlapping existing build reservations first.

Spare targets are nonnegative integer counts per part for the whole workspace.
Omitting them uses `project.json` defaults; an explicit mapping replaces defaults
(`{}` means no spare targets). A spare target may reference a part outside the BOM.

Each planned part reports `physical`, `reserved`, `free`, `incoming`, `demand`,
`spare_target`, `shortage_now`, `additional_to_order`, and `build_shortage_now`.
Only IDs in `stock_counts_verified` have known physical counts. Other physical,
free, and shortage values are `None` (JSON `null`), even if some receipts exist.
`reserved` still reports allocations recorded in the ledger; it does not imply a
verified physical count. A verified part without events has explicit zero stock.

`builds_ready_now` checks build demand alone;
`spare_targets_met_after_builds_now` checks demand plus spare targets.
Both are three-valued: true when all relevant counts prove sufficiency, false
when any known count proves a shortage, and null otherwise. `ok=True` means the
plan was calculated, not that stock is sufficient or the hardware is verified.
Incoming orders can reduce the additional quantity to order; they cannot establish
readiness today. Unknown arrival dates remain in `unknowns`.

## Settled record details

- The existing `0.1-draft` template schema is the supported version. CSV headers
  must match the template. IDs are case-sensitive; quantities are discrete each
  counts. CSV quantities use digits; JSON counts are integers, not booleans.
- Builds used by ledger events require `build_id`, `bom_revision`, and `status` in
  `builds.json`. The revision must exist. Additional build evidence is preserved
  but actual usage/substitutions/test evidence are not yet semantically validated.
- Ordered receipt events require `order_id` and an exact `source` reference of
  `order:<order_id>/<line_id>`, matching the event part. Standalone receipts with
  no order ID are allowed for stock not associated with an order.
- Events replay in **CSV row order**, with timezone-bearing timestamps. Physical,
  reserved, and free balances must remain nonnegative at every location after
  each row; releases and consumption require that build's reservation at that
  location. Adjustments require a reason.
- Event IDs are unique. Operation IDs are unique except a two-event move:
  one adjustment out and one adjustment in with equal part/quantity and different
  locations. A repeated persisted receipt/reservation/consumption operation is
  rejected rather than counted twice. Transaction replay APIs are not implemented.
- Incoming is ordered minus cancelled minus receipts. Planned orders contribute
  nothing. Status must reconcile: `ordered` has no receipts and a positive
  outstanding balance; `partially_received` has receipts and outstanding balance;
  `received` has no outstanding balance; `cancelled` has all units cancelled.
  Partial cancellation without receipts stays `ordered`. Dates never create stock.

## Evidence and limits

The synthetic fixture and focused tests cover the documented planning arithmetic,
partial receipts, reservations, release/consumption, moves, invalid inputs,
unknown versus zero stock, BOM selection, and unchanged record bytes and mtimes.
They do not demonstrate a transaction writer, idempotent mutation API, BOM revision
writer, as-built recorder, resume operation, CLI, MCP, or physical hardware.

Both operations only read files. They do not lock files or offer a coherent snapshot
against concurrent manual edits. The fingerprint identifies the bytes read; it is
not a concurrency guarantee. Use a stable checkout/workspace while validating or
planning. Mutation locking and crash recovery must be implemented before writers.
Engineering suitability, source authenticity, and physical counts remain manual
responsibilities. No component equivalence or project-specific rules are inferred.

## Combined implementation

The implementation combines PR #3's installable `src` package, fingerprint,
structured failure results, explicit order receipt references, move checks, and
three-valued readiness with PR #2's evidence requirements and additional integrity
scenarios. There is one public API: `kicad_engineering_toolkit`; draft imports,
exception-based failures, and bare receipt line references are superseded.

All inventory events require a nonblank evidence source. Only receipts may carry
an order ID. IDs, locations, and adjustment reasons cannot be whitespace-only.
The draft fixture is retained with distinct event operation IDs and a decisions
record to meet the settled contract. Its tests use the same public API.
