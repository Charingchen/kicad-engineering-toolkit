"""Workspace loading, validation, and ledger replay. No record writes."""
import csv
import hashlib
import io
import json
from datetime import date, datetime
from pathlib import Path

HEADERS = {
    "parts.csv": "part_id,description,manufacturer,manufacturer_part_number,variant_or_revision,unit,source,verification_status",
    "bom.csv": "bom_revision,line_id,part_id,quantity_per_build,reference_designators,source",
    "orders.csv": "order_id,line_id,part_id,quantity_ordered,quantity_cancelled,status,expected_arrival,source",
    "inventory-events.csv": "event_id,operation_id,timestamp,event_type,part_id,quantity,location,build_id,order_id,source,reason",
}
FILES = ("project.json", *HEADERS, "builds.json", "decisions.md")


def _integer(value, minimum=0):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= minimum else None
    if isinstance(value, str) and value.isascii() and value.isdecimal():
        number = int(value)
        return number if number >= minimum else None
    return None


def _load(workspace):
    root = Path(workspace)
    records, issues = {}, []
    digest = hashlib.sha256()
    for name in FILES:
        try:
            raw = (root / name).read_bytes()
            digest.update(name.encode() + b"\0" + raw + b"\0")
            text = raw.decode("utf-8-sig")
            if name.endswith(".json"):
                records[name] = json.loads(text)
                if not isinstance(records[name], dict):
                    raise ValueError("expected a JSON object")
            elif name in HEADERS:
                reader = csv.DictReader(io.StringIO(text, newline=""))
                if reader.fieldnames != HEADERS[name].split(","):
                    raise ValueError("CSV header does not match the record contract")
                rows = list(reader)
                if any(None in row or None in row.values() for row in rows):
                    raise ValueError("CSV row has missing or extra columns")
                records[name] = rows
            else:
                records[name] = text
        except (OSError, UnicodeError, ValueError, csv.Error) as exc:
            issues.append({"code": "INVALID_RECORD", "record": name, "message": str(exc)})
    return records, issues, digest.hexdigest()


def _inspect(workspace):
    records, errors, fingerprint = _load(workspace)
    result = {
        "valid": False, "workspace_revision": None,
        "workspace_fingerprint": fingerprint, "input_records": list(FILES),
        "errors": errors, "warnings": [], "unknowns": [],
        "assumptions": ["Discrete each units; ledger rows replay in file order.",
                        "Stock counts are trusted only for stock_counts_verified part IDs."],
        "supported_checks": ["record shape and references", "BOM identities and quantities",
                             "per-location and per-build ledger balances", "order reconciliation"],
    }

    def error(code, record, message):
        errors.append({"code": code, "record": record, "message": message})

    if errors:
        return result, {}
    p = records["project.json"]
    result["workspace_revision"] = p.get("workspace_revision")
    if p.get("schema_version") != "0.1-draft":
        error("INVALID_SCHEMA", "project.json", "expected schema_version 0.1-draft")
    if not isinstance(p.get("workspace_revision"), int) or isinstance(p.get("workspace_revision"), bool) or p["workspace_revision"] < 0:
        error("INVALID_REVISION", "project.json", "workspace_revision must be a nonnegative integer")
    for field in ("project_id", "name", "goal"):
        if not isinstance(p.get(field), str):
            error("INVALID_RECORD", "project.json", f"{field} must be a string")
    if not p.get("project_id"):
        error("INVALID_RECORD", "project.json", "project_id is required")
    for field in ("requirements", "constraints", "open_questions", "evidence"):
        if not isinstance(p.get(field), list):
            error("INVALID_RECORD", "project.json", f"{field} must be a list")
    parts = {}
    for i, row in enumerate(records["parts.csv"], 2):
        ref = f"parts.csv:{i}"
        part = row["part_id"]
        if not part or part in parts:
            error("DUPLICATE_ID" if part else "MISSING_ID", ref, "part_id must be nonempty and unique")
        parts[part] = row
        if row["unit"] != "each" or row["verification_status"] not in {"unverified", "document_checked", "hardware_tested"}:
            error("INVALID_PART", ref, "invalid unit or verification_status")
    verified = p.get("stock_counts_verified")
    if not isinstance(verified, list) or any(not isinstance(x, str) for x in verified):
        error("INVALID_RECORD", "project.json", "stock_counts_verified must be a list of part IDs")
        verified = []
    if len(verified) != len(set(verified)):
        error("DUPLICATE_ID", "project.json", "duplicate verified stock part ID")
    for part in verified:
        if part not in parts:
            error("UNKNOWN_PART", "project.json", f"unknown verified stock part {part}")
    for part in parts:
        if part not in verified:
            result["unknowns"].append({"code": "UNKNOWN_STOCK", "record": "project.json:stock_counts_verified", "part_id": part})
    spares = p.get("spare_targets")
    if not isinstance(spares, dict):
        error("INVALID_RECORD", "project.json", "spare_targets must be an object")
        spares = {}
    for part, qty in spares.items():
        if part not in parts:
            error("UNKNOWN_PART", "project.json:spare_targets", part)
        if not isinstance(qty, int) or isinstance(qty, bool) or qty < 0:
            error("INVALID_QUANTITY", "project.json:spare_targets", part)
    bom, identities = {}, set()
    for i, row in enumerate(records["bom.csv"], 2):
        ref = f"bom.csv:{i}"
        key = row["bom_revision"], row["line_id"]
        if not all(key) or key in identities:
            error("DUPLICATE_ID" if key in identities else "MISSING_ID", ref, "BOM revision/line must be nonempty and unique")
        identities.add(key)
        if row["part_id"] not in parts:
            error("UNKNOWN_PART", ref, row["part_id"])
        qty = _integer(row["quantity_per_build"], 1)
        if qty is None:
            error("INVALID_QUANTITY", ref, "quantity_per_build must be a positive integer")
        bom.setdefault(row["bom_revision"], []).append((row["part_id"], qty or 0))
    active = p.get("active_bom_revision")
    if active is not None and (not isinstance(active, str) or active not in bom):
        error("UNKNOWN_BOM", "project.json", "active_bom_revision does not exist")
    elif active is None:
        result["unknowns"].append({"code": "UNCONFIRMED_INPUT", "record": "project.json:active_bom_revision"})
    b = records["builds.json"]
    if b.get("schema_version") != "0.1-draft" or not isinstance(b.get("builds"), list):
        error("INVALID_RECORD", "builds.json", "expected schema_version and builds list")
        builds = []
    else:
        builds = b["builds"]
    build_ids = set()
    for row in builds:
        if not isinstance(row, dict) or not isinstance(row.get("build_id"), str) or not row["build_id"]:
            error("INVALID_RECORD", "builds.json", "build requires nonempty build_id")
            continue
        if row["build_id"] in build_ids:
            error("DUPLICATE_ID", "builds.json", row["build_id"])
        build_ids.add(row["build_id"])
        if not isinstance(row.get("bom_revision"), str) or row["bom_revision"] not in bom:
            error("UNKNOWN_BOM", "builds.json", row["build_id"])
        if row.get("status") not in {"planned", "reserved", "assembled", "tested", "retired"}:
            error("INVALID_STATUS", "builds.json", row["build_id"])
    orders = {}
    for i, row in enumerate(records["orders.csv"], 2):
        ref = f"orders.csv:{i}"
        key = row["order_id"], row["line_id"]
        if not all(key) or key in orders:
            error("DUPLICATE_ID" if key in orders else "MISSING_ID", ref, "order/line must be nonempty and unique")
        q, c = _integer(row["quantity_ordered"], 1), _integer(row["quantity_cancelled"])
        if q is None or c is None or (q is not None and c is not None and c > q):
            error("INVALID_QUANTITY", ref, "invalid order or cancellation quantity")
        if row["part_id"] not in parts:
            error("UNKNOWN_PART", ref, row["part_id"])
        if row["expected_arrival"]:
            try:
                date.fromisoformat(row["expected_arrival"])
            except ValueError:
                error("INVALID_DATE", ref, "expected_arrival must be an ISO date")
        orders[key] = {**row, "ordered": q or 0, "cancelled": c or 0, "received": 0}
    physical, reserved, allocations = {}, {}, {}
    event_ids, operations = set(), {}
    for i, row in enumerate(records["inventory-events.csv"], 2):
        ref = f"inventory-events.csv:{i}"
        if not row["event_id"] or row["event_id"] in event_ids:
            error("DUPLICATE_ID" if row["event_id"] in event_ids else "MISSING_ID", ref, "event_id must be nonempty and unique")
        event_ids.add(row["event_id"])
        if not row["operation_id"]:
            error("MISSING_ID", ref, "operation_id is required")
        operations.setdefault(row["operation_id"], []).append(row)
        try:
            stamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError()
        except ValueError:
            error("INVALID_TIMESTAMP", ref, "timestamp must include a timezone")
        part, loc, build = row["part_id"], row["location"], row["build_id"]
        qty = _integer(row["quantity"], 1)
        kind = row["event_type"]
        if part not in parts:
            error("UNKNOWN_PART", ref, part)
        if not loc:
            error("MISSING_LOCATION", ref, "location is required")
        if qty is None:
            error("INVALID_QUANTITY", ref, "event quantity must be a positive integer")
            continue
        if kind not in {"receipt", "reserve", "release", "consume", "adjustment_in", "adjustment_out"}:
            error("INVALID_EVENT", ref, kind)
            continue
        key, allocation = (part, loc), (part, loc, build)
        h, r, a = physical.get(key, 0), reserved.get(key, 0), allocations.get(allocation, 0)
        if kind in {"reserve", "release", "consume"}:
            if not build or build not in build_ids:
                error("UNKNOWN_BUILD", ref, "allocation/consumption requires an existing build_id")
            a += qty if kind == "reserve" else -qty
            r += qty if kind == "reserve" else -qty
            if a < 0:
                error("INSUFFICIENT_RESERVATION", ref, "release/consumption exceeds this build's reservation at this location")
        if kind in {"receipt", "adjustment_in"}:
            h += qty
        elif kind in {"consume", "adjustment_out"}:
            h -= qty
        if kind.startswith("adjustment_") and not row["reason"]:
            error("MISSING_REASON", ref, "adjustments require a reason")
        if h < 0 or r < 0 or h < r:
            error("NEGATIVE_BALANCE", ref, "physical/reserved/free balance would be negative")
        physical[key], reserved[key], allocations[allocation] = h, r, a
        if kind == "receipt" and row["order_id"]:
            # Explicit, stable evidence reference: order:<order_id>/<line_id>.
            candidates = [order for (oid, line), order in orders.items()
                          if oid == row["order_id"] and row["source"] == f"order:{oid}/{line}"]
            if len(candidates) != 1 or candidates[0]["part_id"] != part:
                error("UNKNOWN_ORDER_LINE", ref, "receipt source must identify a matching order line")
            else:
                candidates[0]["received"] += qty
    # Operation IDs group only the documented two-event move. Other reuse is
    # rejected: persisted duplicate events must never double-count replayed work.
    for operation, rows in operations.items():
        if len(rows) > 1:
            outs = [x for x in rows if x["event_type"] == "adjustment_out"]
            ins = [x for x in rows if x["event_type"] == "adjustment_in"]
            if not (len(rows) == 2 and len(outs) == len(ins) == 1
                    and outs[0]["part_id"] == ins[0]["part_id"]
                    and _integer(outs[0]["quantity"], 1) == _integer(ins[0]["quantity"], 1)
                    and outs[0]["location"] != ins[0]["location"]):
                error("OPERATION_CONFLICT", "inventory-events.csv", f"reused operation_id {operation}")
    incoming = {part: 0 for part in parts}
    for order in orders.values():
        outstanding = order["ordered"] - order["cancelled"] - order["received"]
        status = order["status"]
        if outstanding < 0:
            error("OVER_RECEIPT", "orders.csv", f"receipts + cancellations exceed {order['order_id']}/{order['line_id']}")
        expected = ("cancelled" if order["cancelled"] == order["ordered"] else
                    "received" if outstanding == 0 else
                    "partially_received" if order["received"] else "ordered")
        if status != expected and not (status == "planned" and not order["received"] and not order["cancelled"]):
            error("INVALID_STATUS", "orders.csv", f"{order['order_id']}/{order['line_id']} status disagrees with quantities")
        if status not in {"planned", "cancelled"} and outstanding > 0:
            incoming[order["part_id"]] = incoming.get(order["part_id"], 0) + outstanding
            if not order["expected_arrival"]:
                result["unknowns"].append({"code": "UNKNOWN_ARRIVAL", "record": "orders.csv", "order_id": order["order_id"], "line_id": order["line_id"]})
    if p.get("open_questions"):
        result["warnings"].append({"code": "OPEN_QUESTIONS", "record": "project.json", "message": "Project has unresolved questions; planning does not verify engineering suitability."})
    result["valid"] = not errors
    return result, {"project": p, "parts": parts, "bom": bom, "physical": physical,
                    "reserved": reserved, "incoming": incoming, "verified": set(verified)}


def validate(workspace):
    """Return structured errors, warnings and unknowns without changing any file."""
    return _inspect(workspace)[0]
