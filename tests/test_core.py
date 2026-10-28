"""Behavioral tests using only synthetic records and the standard library."""
import copy
import csv
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from kicad_engineering_toolkit import build, project

FIXTURE = Path(__file__).parent / "fixtures" / "materials-loop"


class MaterialsLoop(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "workspace"
        shutil.copytree(FIXTURE, self.root)

    def json_edit(self, filename, **changes):
        path = self.root / filename
        value = json.loads(path.read_text())
        value.update(changes)
        path.write_text(json.dumps(value))

    def rows(self, name):
        with (self.root / name).open(newline="") as stream:
            return list(csv.DictReader(stream))

    def write_rows(self, name, rows):
        with (self.root / name).open(newline="") as stream:
            fields = csv.DictReader(stream).fieldnames
        with (self.root / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def event(self, **changes):
        row = dict(event_id="E-new", operation_id="OP-new", timestamp="2026-01-03T00:00:00Z",
                   event_type="receipt", part_id="controller", quantity="1", location="drawer-A",
                   build_id="", order_id="O-1", source="order:O-1/1", reason="")
        row.update(changes)
        rows = self.rows("inventory-events.csv") + [row]
        self.write_rows("inventory-events.csv", rows)

    def codes(self):
        return {e["code"] for e in project.validate(self.root)["errors"]}

    def plan(self, **kwargs):
        return build.plan(self.root, build_count=2, **kwargs)

    def test_acceptance_and_read_only_determinism(self):
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.assertTrue(project.validate(self.root)["valid"])
        result = self.plan()
        self.assertTrue(result["ok"])
        self.assertEqual(result, self.plan())
        ctrl, led = result["parts"]
        self.assertEqual([ctrl[k] for k in ("physical", "reserved", "free", "demand", "spare_target", "incoming", "shortage_now", "additional_to_order")], [3,1,2,2,1,2,1,0])
        self.assertEqual([led[k] for k in ("physical", "reserved", "free", "demand", "incoming", "shortage_now")], [6,2,4,4,0,0])
        self.assertTrue(result["builds_ready_now"])
        self.assertFalse(result["spare_targets_met_after_builds_now"])
        self.assertEqual(result["workspace_revision"], 7)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}
        self.assertEqual(before, after)

    def test_unknown_counts_and_explicit_zero(self):
        self.json_edit("project.json", stock_counts_verified=["led"])
        ctrl = self.plan()["parts"][0]
        for field in ("physical", "free", "shortage_now", "additional_to_order"):
            self.assertIsNone(ctrl[field])
        self.assertEqual(ctrl["reserved"], 1)
        self.assertIsNone(self.plan()["builds_ready_now"])
        self.write_rows("inventory-events.csv", [])
        self.json_edit("project.json", stock_counts_verified=["controller", "led"])
        ctrl = self.plan()["parts"][0]
        self.assertEqual(ctrl["physical"], 0)
        self.assertEqual(ctrl["additional_to_order"], 1)
        self.assertFalse(self.plan()["builds_ready_now"])

    def test_partial_receipt_counts_once_and_status_is_not_receipt(self):
        rows = self.rows("orders.csv")
        rows[0].update(quantity_ordered="4", status="partially_received", expected_arrival="2020-01-01")
        self.write_rows("orders.csv", rows)
        self.event()
        ctrl = self.plan()["parts"][0]
        self.assertEqual((ctrl["physical"], ctrl["incoming"]), (4,3))
        rows[0]["status"] = "received"
        self.write_rows("orders.csv", rows)
        self.assertIn("INVALID_STATUS", self.codes())

    def test_consumption_preserves_free_and_requires_build_location(self):
        self.event(event_type="consume", build_id="B-existing", order_id="", source="fixture")
        ctrl = self.plan()["parts"][0]
        self.assertEqual((ctrl["physical"],ctrl["reserved"],ctrl["free"]), (2,0,2))
        self.event(event_id="E-extra", operation_id="OP-extra", event_type="consume", build_id="B-existing", order_id="", source="fixture")
        self.assertIn("INSUFFICIENT_RESERVATION", self.codes())

    def test_release_and_move(self):
        self.event(event_type="release", build_id="B-existing", order_id="", source="fixture")
        ctrl = self.plan()["parts"][0]
        self.assertEqual((ctrl["physical"],ctrl["reserved"],ctrl["free"]), (3,0,3))
        self.event(event_id="M-out", operation_id="MOVE", event_type="adjustment_out", order_id="", source="fixture", reason="move")
        self.event(event_id="M-in", operation_id="MOVE", event_type="adjustment_in", location="drawer-C", order_id="", source="fixture", reason="move")
        self.assertTrue(project.validate(self.root)["valid"])
        self.assertEqual(self.plan()["parts"][0]["physical"], 3)

    def test_rejects_wrong_build_and_location(self):
        for changes, code in [({"build_id":"other"}, "UNKNOWN_BUILD"), ({"location":"elsewhere"}, "INSUFFICIENT_RESERVATION")]:
            with self.subTest(changes=changes):
                original = self.rows("inventory-events.csv")
                event_args = dict(event_type="consume", order_id="", source="fixture", build_id="B-existing")
                event_args.update(changes)
                self.event(**event_args)
                self.assertIn(code, self.codes())
                self.write_rows("inventory-events.csv", original)

    def test_revision_aggregation_and_project_independence(self):
        rows = self.rows("bom.csv")
        rows += [dict(bom_revision="B",line_id="1",part_id="led",quantity_per_build="2",reference_designators="",source="fixture"),
                 dict(bom_revision="B",line_id="2",part_id="led",quantity_per_build="1",reference_designators="",source="fixture")]
        self.write_rows("bom.csv", rows)
        self.json_edit("project.json", project_id="another-project", active_bom_revision="B")
        self.assertEqual(self.plan(spare_targets={})["parts"][0]["demand"], 6)
        self.assertEqual(self.plan(bom_revision="A")["parts"][1]["demand"], 4)
        self.assertEqual(json.loads((self.root/"builds.json").read_text())["builds"][0]["bom_revision"], "A")

    def test_spare_only_part_and_zero_builds(self):
        result = build.plan(self.root, build_count=0, spare_targets={"led":5})
        self.assertTrue(result["builds_ready_now"])
        self.assertFalse(result["spare_targets_met_after_builds_now"])
        self.assertEqual(result["parts"][1]["shortage_now"], 1)

    def test_order_states_and_cancellations(self):
        rows = self.rows("orders.csv")
        for status, cancelled, incoming in [("planned", "0", 0), ("cancelled", "2", 0), ("ordered", "1", 1)]:
            with self.subTest(status=status):
                rows[0].update(status=status, quantity_cancelled=cancelled)
                self.write_rows("orders.csv", rows)
                result = self.plan()
                self.assertTrue(result["ok"], result["errors"])
                self.assertEqual(result["parts"][0]["incoming"], incoming)
                self.assertEqual(result["parts"][0]["physical"], 3)
        rows[0].update(status="received", quantity_cancelled="1")
        self.write_rows("orders.csv", rows)
        self.event()
        self.assertEqual(self.plan()["parts"][0]["incoming"], 0)
        self.assertTrue(self.plan()["spare_targets_met_after_builds_now"])

    def test_spare_only_part(self):
        rows = self.rows("parts.csv")
        row = dict(rows[0], part_id="spare-only")
        self.write_rows("parts.csv", rows + [row])
        result = self.plan(spare_targets={"spare-only":1})
        spare = result["parts"][2]
        self.assertEqual((spare["part_id"], spare["demand"]), ("spare-only", 0))
        self.assertIsNone(spare["shortage_now"])
        self.assertIsNone(result["spare_targets_met_after_builds_now"])

    def test_negative_location_cannot_be_hidden_by_other_location(self):
        self.event(event_type="adjustment_out", location="empty-drawer", reason="count", order_id="", source="fixture")
        self.assertIn("NEGATIVE_BALANCE", self.codes())

    def test_fingerprint_tracks_content_even_with_same_revision(self):
        before = self.plan()
        self.json_edit("project.json", name="Different synthetic name")
        after = self.plan()
        self.assertEqual(before["workspace_revision"], after["workspace_revision"])
        self.assertNotEqual(before["workspace_fingerprint"], after["workspace_fingerprint"])

    def test_invalid_request_inputs(self):
        for qty in (-1, 1.5, True, "2"):
            self.assertFalse(build.plan(self.root, build_count=qty)["ok"])
        for spares in ({"missing":1}, {"led":-1}, {"led":True}, [], {"led":1.5}):
            self.assertFalse(self.plan(spare_targets=spares)["ok"])
        self.assertFalse(self.plan(bom_revision="missing")["ok"])

    def test_invalid_events_are_blocked_without_partial_plan(self):
        cases = [({"quantity":"1.5"}, "INVALID_QUANTITY"), ({"quantity":"-1"}, "INVALID_QUANTITY"),
                 ({"quantity":"0"}, "INVALID_QUANTITY"), ({"part_id":"missing"}, "UNKNOWN_PART"),
                 ({"event_id":"E-1"}, "DUPLICATE_ID"), ({"operation_id":"OP-1"}, "OPERATION_CONFLICT"),
                 ({"quantity":"3"}, "OVER_RECEIPT"), ({"source":"bad"}, "UNKNOWN_ORDER_LINE"),
                 ({"timestamp":"2026-01-01"}, "INVALID_TIMESTAMP"),
                 ({"event_type":"adjustment_out","quantity":"3","reason":"count"}, "NEGATIVE_BALANCE")]
        original = self.rows("inventory-events.csv")
        for changes, code in cases:
            with self.subTest(changes=changes):
                self.write_rows("inventory-events.csv", original)
                self.event(**changes)
                self.assertIn(code, self.codes())
                self.assertFalse(self.plan()["ok"])
                self.assertEqual(self.plan()["parts"], [])

    def test_bom_integrity(self):
        rows = self.rows("bom.csv")
        self.write_rows("bom.csv", rows + [copy.deepcopy(rows[0])])
        self.assertIn("DUPLICATE_ID", self.codes())
        rows[0]["part_id"] = "missing"
        rows[1]["quantity_per_build"] = "-2"
        self.write_rows("bom.csv", rows)
        self.assertTrue({"UNKNOWN_PART", "INVALID_QUANTITY"} <= self.codes())

    def test_malformed_records_report_errors(self):
        for name, text in [("project.json", "[]"), ("builds.json", '{"builds":null}'),
                           ("bom.csv", "bad,header\n"), ("orders.csv", "not csv")]:
            with self.subTest(name=name):
                original = (self.root/name).read_bytes()
                (self.root/name).write_text(text)
                self.assertFalse(self.plan()["ok"])
                (self.root/name).write_bytes(original)
        (self.root/"parts.csv").unlink()
        self.assertFalse(project.validate(self.root)["valid"])

    def test_empty_template_is_valid_but_unplannable(self):
        result = project.validate(Path(__file__).parents[1]/"templates"/"project")
        self.assertTrue(result["valid"], result["errors"])
        self.assertTrue(result["unknowns"])
        self.assertFalse(build.plan(Path(__file__).parents[1]/"templates"/"project", build_count=1)["ok"])


if __name__ == "__main__":
    unittest.main()
