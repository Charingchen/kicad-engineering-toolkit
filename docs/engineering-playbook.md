# Engineering playbook

This playbook guides an agent helping a maker. Adapt the work to the project's needs while preserving evidence and accurate records.

## Start with intent and unknowns

Capture desired behavior, users, success criteria, budget if known, physical space, power source, and constraints. Separate confirmed facts, user estimates, agent assumptions, and open questions. Ask for the smallest missing fact that blocks useful progress; continue independent work where possible.

Do not choose a board variant from a family name. Record the exact model and revision before pin planning or electrical compatibility checks. Record measured dimensions and their units before asserting that a part fits.

## Choose a practical implementation

Explain when existing modules can meet the goal and when a custom carrier or integrated PCB improves fit, assembly, or functionality. Capture alternatives and the reason for the choice. Prefer the smallest useful prototype that answers the current engineering uncertainty.

For component decisions, record manufacturer documentation, document revision or access date, relevant page/section, operating conditions, and unresolved assumptions. Extracted statements need verification before becoming design constraints. A document link alone is not proof that an integration works.

## Keep design and materials connected

Maintain stable part IDs. Distinguish a proposed substitution from an approved one. For a BOM revision, list added, removed, and changed lines; identify affected unbuilt prototypes, existing orders, and new verification needs. Preserve the configuration of completed builds.

Keep ordered, received, reserved, consumed, and damaged quantities distinct. Record physical storage locations. When a maker reports an arrival or move, propose a concise structured update and show the resulting balance. Never infer arrival from an expected delivery date or infer consumption from a plan.

## Make engineering claims reviewable

Record the check, inputs, limits, result, and evidence. Distinguish calculated margin, tool rule-check output, and measured behavior. An enclosure envelope check does not establish complete assembly fit; ERC/DRC does not establish functional correctness. When supported checks cannot answer a question, return that limit explicitly.

For physical verification, derive tests from requirements: observable behavior, expected power conditions, firmware version, acceptance criteria, and actual result. Leave unperformed tests pending. Record failures and fixes rather than replacing failure history with the final successful result.

## Close a work session

Leave a brief resume note: current revision, completed work, available versus incoming materials, blocked decisions, known failures, and the next useful action. The summary must point to the underlying records. If records conflict or become stale, surface the conflict and reconcile it before claiming the build is ready.
