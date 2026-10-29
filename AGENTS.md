# Repository instructions

## Purpose and current state

Build a reusable, agent-oriented engineering workspace for individual makers. The wand is an example, not a special case in the core. The first read-only Python slice implements project.validate and build.plan with synthetic tests. Record writers, CLI, MCP, and CAD integration remain planned; do not describe them as working features.

## Working conventions

- Read README.md and the relevant docs before changing scope or implementing a feature.
- Use Python for the initial core unless a concrete integration requires another language. Keep calculations and validation independent of the agent, CLI, and MCP transports.
- Preserve stable IDs, BOM revisions, inventory event history, and the exact BOM used by each physical build.
- Missing facts stay unknown. Do not infer a purchased board variant, pin assignment, battery rating, component dimensions, stock quantity, or passed test from a product family name or conversation hint.
- Record engineering claims with a source, revision, assumptions, and verification status. CAD rule checks alone do not establish functional correctness.
- Preview record mutations, validate the expected workspace revision, and apply related updates atomically. Repeated operation IDs must not double-count transactions.
- A planning operation is read-only. Record actual purchases, receipts, allocations, and consumption only when those events are reported or explicitly authorized.
- Never commit credentials, personal receipts, shipping details, or unrelated proprietary files. Use synthetic public fixtures.
- Preserve the existing license and credit reused dependencies. Check current official documentation before choosing a supported KiCad version or API.
- Update documentation when implemented behavior differs from a proposal. Add focused tests for calculation rules, state transitions, and data integrity; avoid tests that only repeat constants or file text.
- Keep changes scoped to the requested milestone. Do not add a UI, full ERP system, autonomous purchasing, or general PCB generation to the first release.

## Validation and delivery

For documentation/template changes, check local links, parse JSON and CSV, and verify that examples agree with the documented rules. For executable changes, run the relevant tests and report what actually ran. Include remaining limitations and manual verification steps.
