# Manual project template

Status: draft record format supported by the read-only [Python validator and planner](../../docs/python-core.md). Record changes are still manual.

Copy this directory into a private project workspace. Use a stock ledger shared by projects when they share physical inventory; never duplicate the same stock into independent project balances. See [architecture](../../docs/architecture.md) for proposed semantics.

## Files

| File | How to use it |
| --- | --- |
| `project.json` | Replace the example ID/name, describe the goal, and record requirements, constraints, and questions |
| `parts.csv` | Add exact items under stable part IDs; use `each` as the initial unit |
| `bom.csv` | Add lines for the chosen revision and quantity per prototype |
| `inventory-events.csv` | Append real receipts, reservations, releases, consumption, and counted adjustments |
| `orders.csv` | Record orders and cancellations; derive receipt quantities from ledger events |
| `builds.json` | Record each prototype's pinned revision, lifecycle, actual parts, and test results |
| `decisions.md` | Keep rationale and supporting sources |

The empty files represent **no data entered**, not verified zero stock. In `project.json`, list a part ID in `stock_counts_verified` only after establishing its usable physical stock at the recorded locations, including an explicit zero count when appropriate. The validator reports uncounted parts as unknown; the planner never claims their availability. Initial nonzero counts use `adjustment_in` events with count evidence. Reconciling later counts requires an adjustment for the difference, not a replacement balance.

## Conventions

- Use unique project, part, event, operation, order, line, and build IDs.
- Quantities are integer discrete counts. Leave unknown optional CSV values blank.
- `source` is a document reference or evidence path, not a claim of verification.
- `verification_status` for parts: `unverified`, `document_checked`, or `hardware_tested`; explain the actual scope in decisions/evidence.
- Inventory `event_type`: `receipt`, `reserve`, `release`, `consume`, `adjustment_in`, `adjustment_out`. Each event has a positive quantity and location. Include build ID for allocations/consumption and order ID for ordered receipts; identify the order line in `source` as `order:<order_id>/<line_id>`.
- Order `status`: `planned`, `ordered`, `partially_received`, `received`, or `cancelled`. Planned requests do not count as incoming. Status must agree with receipts and cancellations; keep partially cancelled unreceived quantities explicit.
- Build records require `build_id`, `bom_revision`, and `status`. Build `status`: `planned`, `reserved`, `assembled`, `tested`, or `retired`. Assembled does not imply tests passed. Record test outcomes separately.
- BOM revisions are project-scoped. Once used by a physical build, keep that revision intact and create a new one for changes.
- Use `workspace_revision` as an increasing integer. Atomic updates, replay protection, and revision checking are future implementation work; manual editing does not enforce them.

## First manual pass

1. Fill the goal and acceptance criteria; leave unknown hardware as an open question.
2. Enter exact known parts and a draft BOM.
3. Count and locate stock, then record orders separately.
4. Calculate a build plan using the documented formula.
5. Record reservations before consumption, then actual build configuration and results.
6. Ask an agent to summarize the records and show any missing facts.
