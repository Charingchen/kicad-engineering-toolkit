"""Deterministic plans for additional, unreserved builds."""
from collections import defaultdict
from .project import InvalidWorkspace, _count, _inspect


def plan(workspace, build_count, *, bom_revision=None, spare_targets=None):
    """Plan from files; overrides replace workspace spare targets, not merge them.

    Unknown stock produces null shortages and blocks readiness. Incoming orders
    reduce additional purchasing only; they never establish readiness today.
    """
    if type(build_count) is not int:
        raise ValueError("build_count must be an integer")
    _count(build_count, True)
    report, state = _inspect(workspace)
    if not report["valid"]:
        raise InvalidWorkspace(report)
    revision = bom_revision if bom_revision is not None else state["project"]["active_bom_revision"]
    if not isinstance(revision, str) or revision not in state["revisions"]:
        raise ValueError("a known BOM revision is required")
    targets = state["project"]["spare_targets"] if spare_targets is None else spare_targets
    if not isinstance(targets, dict):
        raise ValueError("spare_targets must be a mapping")
    for part, quantity in targets.items():
        if part not in state["balances"] or type(quantity) is not int:
            raise ValueError("spare target requires a known part and integer count")
        _count(quantity)
    demand = defaultdict(int)
    for row in state["records"]["bom.csv"]:
        if row["bom_revision"] == revision:
            demand[row["part_id"]] += row["quantity_per_build"] * build_count
    lines = []
    for part in sorted(set(demand) | set(targets)):
        stock = state["balances"][part]
        d, s, free = demand[part], targets.get(part, 0), stock["free"]
        lines.append(dict(part_id=part, **stock, demand=d, spare_target=s,
                          shortage_now=None if free is None else max(0, d+s-free),
                          additional_to_order=None if free is None else max(0, d+s-free-stock["incoming"])))
    return dict(workspace_revision=report["workspace_revision"], bom_revision=revision,
                build_count=build_count, input_records=report["input_records"],
                assumptions=["Additional unreserved builds; no overlap with existing build IDs.",
                             "Verified counts cover all usable stock locations; events are in ledger order."],
                can_assemble_now=all(x["free"] is not None and x["free"] >= x["demand"] for x in lines),
                spare_targets_met_now=all(x["shortage_now"] == 0 for x in lines),
                lines=lines, warnings=report["warnings"], unknowns=report["unknowns"])
