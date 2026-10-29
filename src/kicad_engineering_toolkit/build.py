"""Read-only planning for additional, unreserved builds."""
from .project import _inspect


def plan(workspace, *, build_count, bom_revision=None, spare_targets=None):
    """Plan additional builds. Explicit spare_targets replace workspace defaults.

    Counts are nonnegative integers; spare counts apply across the workspace.
    None values in stock/shortage fields mean unknown, never verified zero.
    Invalid inputs return ok=False with structured errors and no partial plan.
    """
    validation, state = _inspect(workspace)
    result = {key: validation[key] for key in (
        "workspace_revision", "workspace_fingerprint", "input_records",
        "assumptions", "supported_checks", "warnings", "unknowns")}
    result.update(ok=False, errors=list(validation["errors"]), parts=[])
    if not validation["valid"]:
        return result

    def error(code, message):
        result["errors"].append({"code": code, "record": "build.plan", "message": message})

    if type(build_count) is not int or build_count < 0:
        error("INVALID_QUANTITY", "build_count must be a nonnegative integer of additional, unreserved builds")
    revision = state["project"]["active_bom_revision"] if bom_revision is None else bom_revision
    if not isinstance(revision, str) or revision not in state["bom"]:
        error("UNKNOWN_BOM", "select an existing BOM revision")
    spares = state["project"]["spare_targets"] if spare_targets is None else spare_targets
    if not isinstance(spares, dict):
        error("INVALID_QUANTITY", "spare_targets must map part IDs to nonnegative integer counts")
        spares = {}
    for part, qty in spares.items():
        if part not in state["parts"]:
            error("UNKNOWN_PART", f"unknown spare target part {part}")
        if type(qty) is not int or qty < 0:
            error("INVALID_QUANTITY", f"invalid spare target for {part}")
    if result["errors"]:
        return result
    demand = {}
    for part, qty in state["bom"][revision]:
        demand[part] = demand.get(part, 0) + qty * build_count
    result.update(bom_revision=revision, build_count=build_count,
                  spare_targets=dict(spares))
    result["assumptions"] = result["assumptions"] + [
        "Build count means new builds with no existing reservation.",
        "Spare targets are shared-workspace counts, not counts per build.",
        "Incoming quantities are not usable stock today; no delivery schedule is promised.",
    ]
    for part in sorted(demand.keys() | spares.keys()):
        known = part in state["verified"]
        physical = sum(q for (p, _), q in state["physical"].items() if p == part) if known else None
        reserved = sum(q for (p, _), q in state["reserved"].items() if p == part)
        free = physical - reserved if known else None
        d, s, incoming = demand.get(part, 0), spares.get(part, 0), state["incoming"].get(part, 0)
        result["parts"].append({
            "part_id": part, "stock_known": known, "physical": physical,
            "reserved": reserved, "free": free, "incoming": incoming,
            "demand": d, "spare_target": s,
            "shortage_now": max(0, d + s - free) if known else None,
            "additional_to_order": max(0, d + s - free - incoming) if known else None,
            "build_shortage_now": max(0, d - free) if known else None,
        })
    # Three-valued readiness: a known shortage proves false even if another
    # part is uncounted; otherwise uncounted stock leaves readiness unknown.
    def readiness(field):
        values = [row[field] for row in result["parts"]]
        return False if any(v is not None and v > 0 for v in values) else (None if None in values else True)

    result.update(ok=True, builds_ready_now=readiness("build_shortage_now"),
                  spare_targets_met_after_builds_now=readiness("shortage_now"))
    return result
