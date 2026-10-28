"""Load and validate draft workspaces without modifying their records."""
import csv
import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

HEADERS = {
    "parts.csv": "part_id,description,manufacturer,manufacturer_part_number,variant_or_revision,unit,source,verification_status",
    "bom.csv": "bom_revision,line_id,part_id,quantity_per_build,reference_designators,source",
    "inventory-events.csv": "event_id,operation_id,timestamp,event_type,part_id,quantity,location,build_id,order_id,source,reason",
    "orders.csv": "order_id,line_id,part_id,quantity_ordered,quantity_cancelled,status,expected_arrival,source",
}


class InvalidWorkspace(ValueError):
    """Planning failed validation; structured diagnostics are in report."""
    def __init__(self, report):
        self.report = report
        super().__init__("Workspace validation failed")


def _count(value, positive=False):
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        number = int(value)
    else:
        raise ValueError("expected an integer count")
    if number < (1 if positive else 0):
        raise ValueError("count out of range")
    return number


def _inspect(workspace):
    root = Path(workspace)
    errors, warnings, unknowns = [], [], []
    records = {}

    def error(code, record, message):
        errors.append(dict(code=code, record=record, message=message))

    for filename in ["project.json", "builds.json", *HEADERS]:
        try:
            with (root / filename).open(encoding="utf-8", newline="") as stream:
                if filename.endswith("json"):
                    records[filename] = json.load(stream)
                else:
                    reader = csv.DictReader(stream)
                    if reader.fieldnames != HEADERS[filename].split(","):
                        raise ValueError("headers must match the starter template")
                    rows = list(reader)
                    if any(None in row or None in row.values() for row in rows):
                        raise ValueError("CSV row width differs from header")
                    records[filename] = rows
        except (OSError, ValueError, csv.Error) as exc:
            error("INVALID_RECORD", filename, str(exc))

    def report():
        p = records.get("project.json", {})
        return dict(valid=not errors, workspace_revision=p.get("workspace_revision") if isinstance(p, dict) else None,
                    input_records=list(records), errors=errors, warnings=warnings, unknowns=unknowns)

    if errors:
        return report(), None
    p, b = records["project.json"], records["builds.json"]
    if not isinstance(p, dict) or not isinstance(b, dict):
        error("INVALID_RECORD", "project.json/builds.json", "expected JSON objects")
        return report(), None
    try:
        if p.get("schema_version") != "0.1-draft" or b.get("schema_version") != "0.1-draft":
            raise ValueError("only schema_version 0.1-draft is supported")
        if not isinstance(p.get("project_id"), str) or not p["project_id"].strip():
            raise ValueError("project_id must be a nonempty string")
        if type(p.get("workspace_revision")) is not int:
            raise ValueError("workspace_revision must be an integer")
        _count(p["workspace_revision"])
        if not isinstance(p.get("stock_counts_verified"), list):
            raise ValueError("stock_counts_verified must be a list")
        if not all(isinstance(x, str) and x for x in p["stock_counts_verified"]):
            raise ValueError("stock count IDs must be nonempty strings")
        if len(set(p["stock_counts_verified"])) != len(p["stock_counts_verified"]):
            raise ValueError("duplicate stock count IDs")
        if not isinstance(p.get("spare_targets"), dict):
            raise ValueError("spare_targets must be an object")
        if not isinstance(b.get("builds"), list) or not all(isinstance(x, dict) for x in b["builds"]):
            raise ValueError("builds must be an array of objects")
    except ValueError as exc:
        error("INVALID_RECORD", "project.json/builds.json", str(exc))
        return report(), None

    parts, revisions, builds, orders = {}, set(), {}, {}
    seen = defaultdict(set)

    def unique(kind, key, record):
        if any(not isinstance(v, str) or not v.strip() for v in key):
            error("INVALID_ID", record, str(key))
            return
        if key in seen[kind]:
            error("DUPLICATE_ID", record, str(key))
        seen[kind].add(key)

    def part_ref(part, record):
        if part not in parts:
            error("UNKNOWN_PART", record, str(part))

    for row in records["parts.csv"]:
        unique("part", (row["part_id"],), "parts.csv")
        parts[row["part_id"]] = row
        if row["unit"] != "each" or row["verification_status"] not in {"unverified", "document_checked", "hardware_tested"}:
            error("INVALID_RECORD", "parts.csv", "unsupported unit or verification status")
    for row in records["bom.csv"]:
        unique("bom", (row["bom_revision"], row["line_id"]), "bom.csv")
        part_ref(row["part_id"], "bom.csv")
        revisions.add(row["bom_revision"])
        try:
            row["quantity_per_build"] = _count(row["quantity_per_build"], True)
        except ValueError as exc:
            error("INVALID_QUANTITY", "bom.csv", str(exc))
    active = p.get("active_bom_revision")
    if active is None:
        unknowns.append(dict(code="UNCONFIRMED_INPUT", record="project.json", message="active BOM is unknown"))
    elif not isinstance(active, str) or active not in revisions:
        error("UNKNOWN_BOM", "project.json", str(active))
    for row in b["builds"]:
        unique("build", (row.get("build_id"),), "builds.json")
        if not isinstance(row.get("build_id"), str):
            continue
        builds[row["build_id"]] = row
        if not isinstance(row.get("bom_revision"), str) or row["bom_revision"] not in revisions:
            error("UNKNOWN_BOM", "builds.json", str(row.get("bom_revision")))
        if not isinstance(row.get("status"), str) or row["status"] not in {"planned", "reserved", "assembled", "tested", "retired"}:
            error("INVALID_RECORD", "builds.json", "unsupported build status")
    for part in p["stock_counts_verified"]:
        part_ref(part, "project.json")
    for part, value in p["spare_targets"].items():
        part_ref(part, "project.json")
        try:
            if type(value) is not int:
                raise ValueError("spare targets must be JSON integer counts")
            _count(value)
        except ValueError as exc:
            error("INVALID_QUANTITY", "project.json", str(exc))
    for row in records["orders.csv"]:
        key = (row["order_id"], row["line_id"])
        unique("order", key, "orders.csv")
        part_ref(row["part_id"], "orders.csv")
        try:
            row["quantity_ordered"] = _count(row["quantity_ordered"], True)
            row["quantity_cancelled"] = _count(row["quantity_cancelled"])
            if row["quantity_cancelled"] > row["quantity_ordered"]:
                raise ValueError("cancellations exceed ordered quantity")
            if row["expected_arrival"]:
                date.fromisoformat(row["expected_arrival"])
        except ValueError as exc:
            error("INVALID_RECORD", "orders.csv", str(exc))
        orders[key] = row
    for row in records["inventory-events.csv"]:
        unique("event", (row["event_id"],), "inventory-events.csv")
        part_ref(row["part_id"], "inventory-events.csv")
        try:
            row["quantity"] = _count(row["quantity"], True)
            if not row["operation_id"].strip() or not row["location"].strip() or not row["source"].strip():
                raise ValueError("operation_id, location, and evidence source are required")
            if datetime.fromisoformat(row["timestamp"]).utcoffset() is None:
                raise ValueError("event timestamp requires timezone")
            if row["event_type"] not in {"receipt", "reserve", "release", "consume", "adjustment_in", "adjustment_out"}:
                raise ValueError("unsupported event type")
            if row["event_type"].startswith("adjustment") and not row["reason"].strip():
                raise ValueError("adjustments require a reason")
            if row["event_type"] in {"reserve", "release", "consume"} and row["build_id"] not in builds:
                raise ValueError("allocation requires a declared build_id")
            if row["order_id"] and row["event_type"] != "receipt":
                raise ValueError("only receipts may reference orders")
        except ValueError as exc:
            error("INVALID_RECORD", "inventory-events.csv", str(exc))
    if errors:
        return report(), None

    physical, reserved, allocations, received = (defaultdict(int) for _ in range(4))
    for row in records["inventory-events.csv"]:
        part, location, build = row["part_id"], row["location"], row["build_id"]
        key, allocation = (part, location), (part, location, build)
        quantity, kind = row["quantity"], row["event_type"]
        if kind in {"receipt", "adjustment_in"}:
            physical[key] += quantity
        elif kind in {"consume", "adjustment_out"}:
            physical[key] -= quantity
        if kind == "reserve":
            reserved[key] += quantity
            allocations[allocation] += quantity
        elif kind in {"release", "consume"}:
            reserved[key] -= quantity
            allocations[allocation] -= quantity
        if min(physical[key], reserved[key], physical[key] - reserved[key], allocations[allocation]) < 0:
            error("NEGATIVE_BALANCE", row["event_id"], "physical/free/reserved or build allocation became negative")
        if kind == "receipt" and row["order_id"]:
            # Source is an exact line ID; order_id supplies the other half of the key.
            order_key = (row["order_id"], row["source"])
            order = orders.get(order_key)
            if order is None or order["part_id"] != part:
                error("INVALID_ORDER_RECEIPT", row["event_id"], "unknown order line or mismatched part")
            else:
                received[order_key] += quantity
    incoming = defaultdict(int)
    for key, row in orders.items():
        q, c, r = row["quantity_ordered"], row["quantity_cancelled"], received[key]
        status = row["status"]
        remaining = q - c - r
        valid_status = (
            (status == "planned" and c == r == 0)
            or (status == "ordered" and r == 0 and remaining > 0)
            or (status == "partially_received" and r > 0 and remaining > 0)
            or (status == "received" and r > 0 and remaining == 0)
            or (status == "cancelled" and c > 0 and remaining == 0)
        )
        if remaining < 0:
            error("OVER_RECEIPT", "orders.csv", str(key))
        if not valid_status:
            error("INVALID_ORDER_STATUS", "orders.csv", str(key))
        if status != "planned":
            incoming[row["part_id"]] += remaining
    balances = {}
    for part in parts:
        known = part in p["stock_counts_verified"]
        h = sum(q for (pid, _), q in physical.items() if pid == part)
        r = sum(q for (pid, _), q in reserved.items() if pid == part)
        balances[part] = dict(physical=h if known else None, reserved=r,
                              free=h-r if known else None, incoming=incoming[part])
        if not known:
            unknowns.append(dict(code="UNKNOWN_STOCK", record="project.json", message=part))
    warnings.append(dict(code="LIMITED_VALIDATION", record="builds.json", message="Actual usage, substitutions, test evidence, historical edits and transaction replay are not validated in this slice."))
    return report(), dict(project=p, records=records, balances=balances, revisions=revisions)


def validate(workspace):
    """Return structured errors, warnings and unknowns; never write records."""
    return _inspect(workspace)[0]
