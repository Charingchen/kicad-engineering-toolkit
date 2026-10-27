# Product scope

## Product hypothesis

Individual makers building small electronic objects need help maintaining engineering context across design changes, purchases, assembly, and long pauses between sessions. A workspace that connects those records to an agent may reduce rework and make the next action easier to identify.

The first audience is a maker combining a small controller, simple peripherals, firmware, and a printed enclosure. Custom PCBs are useful when packaging or wiring justifies them; a working module-based prototype is a valid outcome.

## What makes this worth building

The proposed value is the connection between engineering intent and physical project state. A BOM change should explain its impact on unbuilt prototypes and purchasing, while completed builds retain their actual configuration. A resume summary should distinguish an unverified assumption from a tested result.

An MCP transport or a chat interface alone would not prove that value. The first validation is a complete, reproducible project-management loop with fewer manual reconciliations.

## First release

- Initialize a portable project workspace.
- Maintain requirements, unknowns, source references, and decisions.
- Maintain a part catalog and immutable released BOM revisions.
- Record orders separately from receipts and track usable stock by location.
- Calculate build shortages with existing reservations and explicit spare targets.
- Record reservations and actual consumption for a prototype.
- Preserve as-built configuration and test evidence.
- Produce a useful resume summary from the records.

## Later integrations

Mechanical envelope checks; KiCad BOM import and connectivity inspection; controlled design changes; firmware pin definitions; datasheet evidence capture; inventory-system adapters. Each should use the shared project model rather than create an independent source of truth.

## Initial exclusions

General automatic circuit synthesis or routing, unrestricted CAD editing, automatic purchases, live supplier pricing, a hosted multi-user service, and a full inventory/ERP replacement. Battery charging circuit design is not part of the first demonstration.

## Assumptions to test

| Assumption | Evidence to seek |
| --- | --- |
| Makers will maintain enough records for the agent to help | Observe update effort during a real prototype build |
| Structured operations improve on a prompt and a spreadsheet | Compare missing facts, reconciliation work, and time to plan the next build |
| The core is reusable | Run the same workflow for a second project without project-specific code |
| This is useful beyond its author | Have a few other makers resume a project and produce a correct shortage list |
| A business could support itself | Separately measure willingness to pay and troubleshooting time; portfolio value does not establish market demand |

## Definition of a credible portfolio

A reviewer can reproduce one complete workflow, inspect its source records and calculations, see an intentional failure caught, and identify exactly what the author implemented. Physical fit, electrical behavior, and firmware claims require actual build evidence when those capabilities are added.
