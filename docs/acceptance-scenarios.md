# Acceptance scenarios for the first implementation

The first read-only slice tests the two-prototype arithmetic, incoming/partial receipt distinction, existing ledger transitions, revision selection, and invalid/unknown inputs. See [test command and scope](python-core.md). Mutation/replay, BOM editing, actual build-history preservation, and resume scenarios below remain future specifications. All parts and quantities here are synthetic bookkeeping examples, not a wiring or hardware recommendation.

## Two prototypes and a spare

BOM revision A requires one controller and two LEDs per prototype. There are three controllers and six LEDs physically on hand. Another build has reserved one controller and two LEDs. Two controllers are on order and none has arrived.

Request two additional prototypes, retaining one controller as a free spare and zero spare LEDs.

| Part | Physical H | Reserved R | Free H−R | New demand D | Spare target S | Incoming I | Short now | Additional order |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Controller | 3 | 1 | 2 | 2 | 1 | 2 | 1 | 0 |
| LED | 6 | 2 | 4 | 4 | 0 | 0 | 0 | 0 |

The report explains that the builds have enough free parts to assemble, but the controller spare target is not met today. Receiving one incoming controller satisfies that target. Planning does not create reservations, consumption, or an order.

## Partial receipt and replay

Order four controllers. Receive one under a unique operation ID. Physical stock rises by one; outstanding incoming quantity is three. Replay the identical operation: neither value changes. Reuse its ID for quantity two: reject the conflict. An over-receipt is rejected. An expected arrival date passing does not add stock.

## Reservation to consumption

With two controllers at drawer A, reserve one for build B-001. Physical stock remains two, reserved becomes one, and free becomes one. Consume that controller for B-001: physical becomes one, reserved becomes zero, and free remains one. Replaying the operation changes nothing. Consumption for a different build or beyond the reservation fails without modifying records.

## BOM revision and actual build history

Complete B-001 using revision A with two LEDs. Create revision B requiring three LEDs. B-001 still references A and its actual two LEDs. Planning two new builds on B requires six LEDs. If a substitution is used, record the actual part and rationale and consume that part's inventory; do not silently rewrite A.

## Invalid and unknown inputs

Reject unknown part IDs, duplicate event IDs, non-integer/negative quantities, duplicate BOM line IDs within a revision, and ledger events that create negative balances. An uncounted part has unknown availability; the summary must not call it ready or treat an estimated count as verified.

## Resume and reproducibility

Close the agent session and recreate a summary from files only. It identifies the active BOM, B-001's pinned revision, free/reserved/incoming quantities, unresolved questions, pending tests, and next action, citing the records. Running the same scenario with another project ID produces the same arithmetic without project-specific code.
