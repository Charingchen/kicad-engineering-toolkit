# Roadmap

The first read-only slice of Milestone 1 is implemented: Python validation and build planning, a synthetic fixture, and focused automated tests. Other executable capabilities below remain planned; Milestone 1 is not complete.

## Milestone 0 — shared foundation

Deliver the product scope, architecture, playbook, starter records, and acceptance scenarios. This establishes the contract for implementation; it is not an automated product demo.

## Milestone 1 — one complete materials loop

Implement a Python core and a small CLI for workspace initialization/validation, BOM revisions, inventory events, build planning, and build recording. Settle the draft record contract while implementing; add focused tests and an offline fixture.

Completion means a user can start a project, enter a BOM, record an order and partial receipt, reserve and consume parts for one prototype, plan two more with a spare target, and obtain a correct resume summary. Repeating operations must not duplicate receipts or consumption. A BOM revision must preserve the first build's history. The acceptance scenarios must run automatically from a clean checkout with documented commands.

The initial implementation should be achievable without KiCad installed, supplier accounts, or a paid AI service. This keeps the domain behavior reproducible before adding integrations.

## Milestone 2 — one agent-guided loop

Expose the proven core operations through MCP and document direct Python use. Demonstrate a natural-language request that produces a plan, an explained preview, an authorized update, and a later resume. Capture tool calls, record diffs, and failures; do not replace deterministic calculations with model arithmetic.

Completion means the same records and invariants work through each interface, and a second project runs by changing data. Evaluate manual bookkeeping effort and mistakes against the prior workflow.

## Milestone 3 — engineering integrations

Confirm the exact reference hardware and collect its source documentation. Add explicit dimensions, mechanical envelope checks, and limited KiCad read access as needed for that build. Check official KiCad documentation at implementation time and pin tested versions. Document adapter capabilities and licenses; do not claim support for untested schematic or PCB operations.

Completion means one real build has documented assembly, firmware, fit checks, electrical/functional results, and as-built records. A deliberately invalid configuration must be caught by a supported check. Add controlled CAD edits only after the read/validate workflow is reliable.

## Evidence to publish

- A short demo and a reproducible transcript tied to a repository commit.
- A correct shortage calculation, an incoming-order distinction, and an intentional failure.
- BOM change impact and preserved prototype history.
- What was implemented, reused, entered manually, and physically verified.
- Results from another project and feedback from other makers before expanding product scope.

## First implementation slice

`project.validate` and read-only `build.plan` now run against the synthetic materials-loop fixture. See [Python core](python-core.md) for reproducible test/demo commands and remaining limitations. They preserve unknown stock, distinguish physical/reserved/free/incoming quantities, and do not modify records. Next implement inventory transactions with locking, crash recovery and replay protection, then build history before adding a transport layer.
