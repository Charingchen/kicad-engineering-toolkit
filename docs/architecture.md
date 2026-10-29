# Proposed architecture and records

Status: `project.validate` and read-only `build.plan` are implemented in Python. The remaining operations and transports are proposals. See [Python core](python-core.md) for API signatures, supported checks, and settled draft record details.

## Shared core

The agent interprets goals, gathers missing inputs, and proposes actions. A Python domain layer validates records and performs deterministic calculations. Python callers, a CLI, and MCP should call that same layer. KiCad and inventory services are adapters, added only when needed.

Begin with JSON, CSV, and Markdown records for inspection and Git review. Avoid committing to a database or an external inventory service until a working workflow shows what is required.

## Proposed operations

These are shared operation names, not installed commands. Only validation and planning have implemented Python APIs in this slice.

| Operation | Inputs and result | Effect |
| --- | --- | --- |
| `project.init` | Goal and project ID → starter workspace | Create records |
| `project.validate` | Workspace → errors, warnings, unknowns | Read only |
| `project.resume` | Workspace → current state, blockers, next actions | Read only |
| `bom.revise` | Base BOM, edits, rationale → new revision and impact | Preview then commit |
| `inventory.record` | Event ID, part, quantity, location, evidence → updated ledger | Preview then commit |
| `build.plan` | BOM revision, new build count, spare targets → explained shortages | Read only |
| `build.reserve` | Plan and operation ID → allocation | Preview then commit |
| `build.record` | Build ID, BOM revision, actual usage, results → as-built record | Preview then commit |

Every result should identify the workspace revision, relevant input records, assumptions, and supported checks. Use structured errors such as `UNKNOWN_PART`, `INSUFFICIENT_STOCK`, `REVISION_CONFLICT`, and `UNCONFIRMED_INPUT` rather than silently patching data.

## Starter record model

The template is a draft contract. CSV identifiers are case-sensitive strings; quantities are integer counts of discrete items in v1. Empty CSVs contain a header only. Unknown optional values are blank in CSV and null in JSON. Dates use ISO 8601; event timestamps include a timezone.

| Record | Identity and meaning |
| --- | --- |
| `project.json` | Project ID, goal, requirements, constraints, unresolved questions, active BOM revision, workspace revision |
| `parts.csv` | Stable `part_id`; manufacturer and exact variant; unit is `each`; evidence link and verification state |
| `bom.csv` | Unique `(bom_revision, line_id)`; `part_id`, quantity per build, optional reference designators and source |
| `inventory-events.csv` | Immutable `event_id`, operation ID, type, part, positive quantity, location, optional build/order ID, timestamp, source |
| `orders.csv` | Unique `(order_id, line_id)`; part, ordered quantity, cancelled quantity, status, expected arrival, evidence |
| `builds.json` | Build plans/instances with pinned BOM revision, lifecycle, actual component usage, substitutions, and test evidence |
| `decisions.md` | Dated reasoning, alternatives, source references, and verification status |

`parts.csv` and `bom.csv` have different jobs: a part describes an item; a BOM line states how many a particular design requires. A manufacturer part change creates a new part ID. Released BOM revisions remain available. Requirements and constraints can start as text with stable IDs; typed mechanical/electrical constraints come with their validators later.

## Inventory event semantics

Positive quantities are interpreted by event type. A receipt adds physical stock. A reservation reduces free stock but not physical stock. A release undoes a reservation. A consumption event removes physical stock and the same quantity of that build's reservation. Consumption in v1 requires a reservation for the same part and location. Adjustments in/out reconcile counted stock with a recorded reason. A move uses paired adjustment events under one operation ID with equal part/quantity and different locations.

For each part and location:

- Physical stock = receipts + adjustments in − consumption − adjustments out.
- Reserved stock = reservations − releases − consumption.
- Free stock = physical stock − reserved stock.

Reject negative balances, consumption exceeding the build's reservation, and adjustments that strand reservations. Quarantined or defective parts are outside usable stock; record their removal with a reason. Unknown initial stock is not zero verified stock: require a physical count or report an unknown before promising availability.

An order is not stock. Receipt events refer to their order line in the source field; total receipts and cancellations cannot exceed the line's ordered quantity. Outstanding ordered quantity = ordered − cancelled − received. Marking an order received does not create a second receipt. Partial receipts remain explicit.

## Build planning

For each part, let `D` be demand for the requested new builds, `S` the desired free spare count after those builds, `H` physical usable stock, `R` existing reservations, and `I` outstanding incoming orders. Spare targets are counts per part across the shared workspace, not counts per prototype. V1 uses one workspace stock ledger; projects sharing parts must reference it rather than copy balances.

- Free stock now: `H − R`.
- Shortage now: `max(0, D + S − (H − R))`.
- Additional quantity to order after incoming orders: `max(0, D + S − (H − R) − I)`.

Report both shortages. Incoming parts cannot make a build ready today; unknown delivery dates remain unknown. A plan also reports missing/unknown stock counts. Build count means additional, unreserved builds; if a request overlaps an existing reservation, resolve its build IDs instead of counting it again. These simple rules do not promise scheduling or supplier optimization.

## Integrity and change history

Mutations validate an expected workspace revision and use a unique operation ID. Related record changes commit together or leave the workspace unchanged. Replaying an identical operation is a no-op returning its prior result; reusing its ID with different content is an error. Git history helps review but does not replace these rules.

Each physical build pins a BOM revision and retains actual usage and test evidence. A later BOM edit cannot rewrite its history. Substitutions require an explicit mapping and engineering rationale; the planning layer cannot assume electrical equivalence. Stock depletion follows actual usage, not the nominal BOM alone.

The read-only implementation does not lock files or guarantee snapshots during concurrent manual edits. Before implementing file transactions, define locking and crash recovery. Records remain manually maintained; there is no claim of concurrency safety.
