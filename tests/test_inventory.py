"""Transaction behavior and interruption tests on synthetic local workspaces."""
import csv
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from kicad_engineering_toolkit import build, inventory, project
from kicad_engineering_toolkit import _transactions as tx

FIXTURE = Path(__file__).parent / 'fixtures' / 'materials-loop'


class InventoryTransactions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        shutil.copytree(FIXTURE, self.root)
        self.initial = project.validate(self.root)
        self.event = dict(event_id='receipt-new', operation_id='receive-new',
                          timestamp='2026-10-29T00:00:00Z', event_type='receipt',
                          part_id='controller', quantity=1, location='drawer-A',
                          order_id='O-1', source='order:O-1/1')

    def record(self, events=None, apply=False, **changes):
        request = dict(events=events if events is not None else [self.event],
                       expected_workspace_revision=self.initial['workspace_revision'],
                       expected_workspace_fingerprint=self.initial['workspace_fingerprint'],
                       apply=apply)
        request.update(changes)
        return inventory.record(self.root, **request)

    def snapshot(self):
        return {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.root.iterdir()}

    def assert_code(self, result, code):
        self.assertFalse(result['ok'], result)
        self.assertIn(code, {e['code'] for e in result['errors']}, result)

    def test_preview_is_deterministic_and_never_creates_or_changes_files(self):
        before = self.snapshot()
        preview = self.record()
        self.assertTrue(preview['ok'], preview)
        self.assertEqual(preview, self.record())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(preview['workspace_revision'], 8)
        self.assertEqual(set(preview['changed_records']),
                         {'inventory-events.csv', 'orders.csv', 'project.json'})

    def test_apply_receipt_reconciles_orders_preserves_history_and_replays(self):
        ledger = (self.root/'inventory-events.csv').read_bytes()
        original_builds = (self.root/'builds.json').read_bytes()
        result = self.record(apply=True)
        self.assertTrue(result['ok'], result)
        self.assertTrue((self.root/'inventory-events.csv').read_bytes().startswith(ledger))
        self.assertEqual(original_builds, (self.root/'builds.json').read_bytes())
        plan = build.plan(self.root, build_count=2)
        self.assertEqual((plan['parts'][0]['physical'], plan['parts'][0]['incoming']), (4, 1))
        self.assertEqual(plan['workspace_revision'], 8)
        self.assertEqual(result['workspace_fingerprint'], plan['workspace_fingerprint'])
        before = self.snapshot()
        self.assertEqual(self.record(apply=True), result)  # original stale revision is intentional
        self.assertEqual(self.snapshot(), before)
        self.event['quantity'] = 2
        self.assert_code(self.record(apply=True), 'OPERATION_CONFLICT')
        self.assertEqual(self.snapshot(), before)

    def test_final_receipt_status_and_stale_requests(self):
        self.event['quantity'] = 2
        self.assertTrue(self.record(apply=True)['ok'])
        orders = list(csv.DictReader(io.StringIO((self.root/'orders.csv').read_text())))
        self.assertEqual(orders[0]['status'], 'received')
        other = dict(self.event, event_id='another', operation_id='another')
        self.assert_code(self.record([other], apply=True), 'REVISION_CONFLICT')

    def test_stale_fingerprint_even_without_revision_change(self):
        p = self.root/'decisions.md'
        p.write_text(p.read_text() + '\nNew evidence\n')
        before = self.snapshot()
        self.assert_code(self.record(), 'REVISION_CONFLICT')
        self.assertEqual(before, self.snapshot())
        self.assert_code(self.record(expected_workspace_revision=6), 'REVISION_CONFLICT')

    def test_invalid_events_fail_without_record_changes(self):
        cases = [dict(quantity=9), dict(quantity=True), dict(part_id='unknown'),
                 dict(event_id='E-1'), dict(source=''), dict(source='1'),
                 dict(operation_id='OP-1'), dict(event_type='consume', build_id='B-existing'),
                 dict(event_type='adjustment_out', quantity=3, order_id='', reason='damaged')]
        for changes in cases:
            with self.subTest(changes=changes):
                before = self.snapshot()
                result = self.record([dict(self.event, **changes)])
                self.assertFalse(result['ok'], result)
                self.assertEqual(before, self.snapshot())

    def test_lock_contention_across_processes(self):
        with tx.locked(self.root):
            code = '''import json,sys
from kicad_engineering_toolkit import inventory
print(json.dumps(inventory.recover(sys.argv[1])))'''
            child = subprocess.run([sys.executable, '-c', code, str(self.root)],
                                   capture_output=True, text=True, check=True)
            self.assert_code(json.loads(child.stdout), 'WORKSPACE_LOCKED')
            self.assertTrue(project.validate(self.root)['valid'])

    def test_interrupt_every_replacement_and_recover_complete_generation(self):
        # journal publication + each of four record replacements; covers a
        # committed but not cleaned-up journal as well as partial publication.
        original_replace = tx.replace
        for point in range(1, 6):
            with self.subTest(point=point):
                shutil.rmtree(self.root)
                shutil.copytree(FIXTURE, self.root)
                calls = 0
                def interrupted(root, name, content):
                    nonlocal calls
                    original_replace(root, name, content)
                    calls += 1
                    if calls == point:
                        raise OSError('simulated interruption after durable replacement')
                with patch.object(tx, 'replace', interrupted):
                    self.assert_code(self.record(apply=True), 'IO_ERROR')
                before = self.snapshot()
                validation = project.validate(self.root)
                self.assertFalse(validation['valid'])
                self.assertIn('RECOVERY_REQUIRED', {e['code'] for e in validation['errors']})
                self.assertFalse(build.plan(self.root, build_count=2)['ok'])
                self.assert_code(self.record(), 'RECOVERY_REQUIRED')
                self.assertEqual(self.snapshot(), before)  # readers never repair
                self.assertTrue(inventory.recover(self.root)['recovered'])
                plan = build.plan(self.root, build_count=2)
                self.assertEqual((plan['workspace_revision'], plan['parts'][0]['physical']), (8, 4))
                self.assertEqual(self.record(apply=True)['workspace_fingerprint'], plan['workspace_fingerprint'])
                self.assertFalse(inventory.recover(self.root)['recovered'])

    def test_process_exit_releases_lock_and_recovery_can_be_interrupted_again(self):
        code = """import os,sys
from pathlib import Path
from kicad_engineering_toolkit import inventory, project, _transactions as tx
root=Path(sys.argv[1])
event=__import__('json').loads(sys.argv[2])
old=tx.replace
def die(root,name,content):
    old(root,name,content)
    if name == 'inventory-events.csv': os._exit(23)
tx.replace=die
p=project.validate(root)
inventory.record(root, events=[event], expected_workspace_revision=p['workspace_revision'],
                 expected_workspace_fingerprint=p['workspace_fingerprint'], apply=True)
"""
        child = subprocess.run([sys.executable, '-c', code, str(self.root), json.dumps(self.event)])
        self.assertEqual(child.returncode, 23)
        self.assertFalse(project.validate(self.root)['valid'])
        old = tx.replace
        def fail_again(root, name, content):
            old(root, name, content)
            if name == 'orders.csv':
                raise OSError('recovery also interrupted')
        with patch.object(tx, 'replace', fail_again):
            self.assert_code(inventory.recover(self.root), 'IO_ERROR')
        self.assertTrue(inventory.recover(self.root)['recovered'])
        self.assertEqual(build.plan(self.root, build_count=1)['parts'][0]['physical'], 4)

    def test_manual_operation_cannot_be_adopted_and_planned_order_cannot_receive(self):
        self.assert_code(self.record([dict(self.event, operation_id='OP-1')]), 'OPERATION_CONFLICT')
        path = self.root/'orders.csv'
        path.write_text(path.read_text().replace(',ordered,', ',planned,'))
        self.initial = project.validate(self.root)
        before = self.snapshot()
        self.assert_code(self.record(), 'INVALID_STATUS')
        self.assertEqual(before, self.snapshot())

    def test_failure_before_journal_publication_leaves_records_unchanged(self):
        before = {name: (self.root/name).read_bytes() for name in project.FILES}
        with patch.object(tx, 'replace', side_effect=OSError('disk full')):
            self.assert_code(self.record(apply=True), 'IO_ERROR')
        self.assertFalse((self.root/tx.JOURNAL).exists())
        self.assertEqual(before, {name: (self.root/name).read_bytes() for name in project.FILES})
        self.assertTrue(project.validate(self.root)['valid'])

    def test_recovery_conflicting_edit_checks_all_files_before_writing(self):
        with patch.object(tx, 'finish', side_effect=OSError('interrupted')):
            self.assert_code(self.record(apply=True), 'IO_ERROR')
        (self.root/'project.json').write_text('{}')
        before = self.snapshot()
        self.assert_code(inventory.recover(self.root), 'RECOVERY_CONFLICT')
        self.assertEqual(before, self.snapshot())

    def test_history_tampering_blocks_readers_and_writers(self):
        self.assertTrue(self.record(apply=True)['ok'])
        ledger = self.root/'inventory-events.csv'
        ledger.write_bytes(ledger.read_bytes().replace(b'fixture-count', b'edited-source'))
        before = self.snapshot()
        self.assertIn('HISTORY_CONFLICT', {e['code'] for e in project.validate(self.root)['errors']})
        self.assert_code(self.record(apply=True), 'HISTORY_CONFLICT')
        self.assertEqual(before, self.snapshot())

    def test_unknown_stock_remains_unknown(self):
        path = self.root/'project.json'
        p = json.loads(path.read_text()); p['stock_counts_verified'] = ['led']
        path.write_text(json.dumps(p)); self.initial = project.validate(self.root)
        self.assertTrue(self.record(apply=True)['ok'])
        plan = build.plan(self.root, build_count=2)
        self.assertIsNone(plan['parts'][0]['physical'])
        self.assertIsNone(plan['builds_ready_now'])

    def test_generation_change_during_read_is_rejected(self):
        original = tx.marker
        count = 0
        def changed(root):
            nonlocal count
            count += 1
            return original(root) if count == 1 else b'new generation'
        with patch.object(tx, 'marker', changed):
            result = project.validate(self.root)
        self.assertFalse(result['valid'])
        self.assertIn('REVISION_CONFLICT', {e['code'] for e in result['errors']})

    def test_move_and_reservation_consumption_replay(self):
        self.event.update(event_type='consume', order_id='', source='synthetic', build_id='B-existing')
        self.assertTrue(self.record(apply=True)['ok'])
        plan = build.plan(self.root, build_count=1)
        self.assertEqual((plan['parts'][0]['physical'], plan['parts'][0]['reserved']), (2, 0))
        self.assertTrue(self.record(apply=True)['ok'])
        self.initial = project.validate(self.root)
        move = dict(self.event, event_id='move-out', operation_id='move', event_type='adjustment_out',
                    build_id='', reason='move')
        incoming = dict(move, event_id='move-in', event_type='adjustment_in', location='drawer-C')
        self.assertTrue(self.record([move, incoming], apply=True)['ok'])
        self.assertEqual(build.plan(self.root, build_count=1)['parts'][0]['physical'], 2)

    def test_malformed_journal_and_metadata_fail_closed(self):
        for value in ('[]', '{broken', '{"version":1,"files":{}}'):
            (self.root/tx.JOURNAL).write_text(value)
            self.assert_code(inventory.recover(self.root), 'INVALID_JOURNAL')
            (self.root/tx.JOURNAL).unlink()
        (self.root/tx.STATE).write_text('[]')
        self.assert_code(self.record(), 'INVALID_TRANSACTION_STATE')
        self.assertFalse(project.validate(self.root)['valid'])


if __name__ == '__main__':
    unittest.main()
