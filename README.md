# KiCad Engineering Toolkit

An agent-oriented workspace for starting, managing, and resuming small hardware projects.

The goal is to let an individual maker describe what they want to build, then work with an AI agent that follows engineering practices and maintains durable project records: requirements, decisions, BOM revisions, purchases, parts locations, and prototype history. KiCad is one planned integration within that workflow.

**Status: Python validation, planning, and inventory transactions implemented.** `project.validate` and `build.plan` run against the file records, with a synthetic fixture and focused tests. `inventory.record` previews and explicitly applies events with replay protection and recovery; see [inventory transactions](docs/inventory-transactions.md). Other record writers, CLI, MCP, CAD integration, and validated hardware designs remain planned. See the [Python core guide](docs/python-core.md) for reproducible commands and limitations.

## The problem

Building a second prototype often means reconstructing the first: which BOM was used, what changed, which parts are already installed, what is still on order, and where the remaining parts are stored. A chat transcript alone is a poor source of truth for those details.

This toolkit aims to keep that information consistent while the agent helps move the engineering work forward.

## Intended workflow

1. Start a project from a plain-language goal and record unknowns.
2. Establish requirements, constraints, and a revisioned BOM.
3. Record purchases, actual receipts, and storage locations.
4. Plan a build using available stock and explicit spare targets.
5. Record the parts consumed, substitutions, and test results for each prototype.
6. Resume later with an accurate summary of progress and the next useful action.

For example: **“Build two more prototypes and keep one controller spare.”** The planned tool would identify the applicable BOM, account for existing allocations, distinguish received parts from incoming orders, and return an explained shortage list. A plan would not consume stock or place an order.

## Start here

Use the templates manually and run the read-only Python operations to validate records and calculate materials plans.

1. Copy [templates/project](templates/project) into your own project workspace.
2. Follow the [template guide](templates/project/README.md) to fill in the records.
3. Use the [engineering playbook](docs/engineering-playbook.md) with your agent.
4. Review the [first milestone](docs/roadmap.md) before implementing tools.

Keep personal purchasing records and proprietary project files in a private workspace. Examples committed here should be synthetic or explicitly cleared for publication.

## Repository map

| Path | Purpose |
| --- | --- |
| [docs/python-core.md](docs/python-core.md) | Implemented Python API, tests, record details, and limitations |
| [docs/product-scope.md](docs/product-scope.md) | Target user, boundaries, and assumptions to test |
| [docs/architecture.md](docs/architecture.md) | Shared operations, records, and planned interfaces |
| [docs/engineering-playbook.md](docs/engineering-playbook.md) | Guidance for agent-assisted engineering |
| [docs/roadmap.md](docs/roadmap.md) | Milestones and measurable completion criteria |
| [docs/acceptance-scenarios.md](docs/acceptance-scenarios.md) | Concrete examples for the first implementation |
| [templates/project](templates/project) | Portable starter records for a new project |
| [examples/wand/README.md](examples/wand/README.md) | First candidate application and unresolved inputs |
| [AGENTS.md](AGENTS.md) | Instructions for agents contributing to this repository |

## Implementation direction

Build a small Python core with deterministic validation and inventory calculations. Expose the same operations to direct Python calls, a CLI, and eventually MCP. The AI handles conversation and planning; the core enforces record integrity and returns evidence. Start with files that can be reviewed in Git, then consider database or inventory-system adapters when the first workflow demonstrates a need.

The first useful release should complete the project/BOM/stock/build loop. Mechanical constraints, KiCad read access, and controlled design edits follow that foundation. Automatic circuit generation and routing are outside the initial scope.

## Portfolio evidence

Progress should be demonstrated through reproducible examples, before/after records, meaningful failure cases, and eventually a physical build. Document manual steps and distinguish implemented behavior from proposals. A second project should reuse the same operations by changing its data, without adding project-specific branches to the core.

## License

See [LICENSE](LICENSE). Third-party tools and reference material retain their own licenses; each integration must document its source and license before code is reused.
