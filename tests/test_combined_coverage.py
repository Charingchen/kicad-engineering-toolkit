import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from kicad_engineering_toolkit import build, project

FIXTURE = Path(__file__).parent / 'fixtures' / 'materials'


class MaterialsCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'workspace'
        shutil.copytree(FIXTURE, self.root)

    def rows(self, name):
        with (self.root/name).open(newline='') as f:
            reader = csv.DictReader(f)
            return reader.fieldnames, list(reader)

    def edit_rows(self, name, edit):
        header, rows = self.rows(name)
        edit(rows)
        with (self.root/name).open('w', newline='') as f:
            writer = csv.DictWriter(f, header)
            writer.writeheader()
            writer.writerows(rows)

    def edit_json(self, name, edit):
        data = json.loads((self.root/name).read_text())
        edit(data)
        (self.root/name).write_text(json.dumps(data))

    def event(self, **overrides):
        row = dict(event_id='E5', operation_id='synthetic-operation', timestamp='2026-01-03T00:00:00Z',
                   event_type='receipt', part_id='controller', quantity='1', location='drawer',
                   build_id='', order_id='', source='synthetic', reason='')
        row.update(overrides)
        row['operation_id'] = overrides.get('operation_id', row['event_id'])
        self.edit_rows('inventory-events.csv', lambda rows: rows.append(row))

    def assert_invalid(self, code):
        report = project.validate(self.root)
        self.assertFalse(report['valid'], report)
        aliases = {
            'INVALID_RECORD': {'INVALID_RECORD', 'UNKNOWN_BUILD', 'INVALID_QUANTITY', 'INVALID_TIMESTAMP', 'INVALID_EVENT', 'MISSING_LOCATION', 'MISSING_ID', 'MISSING_REASON', 'INVALID_REVISION'},
            'INVALID_ID': {'INVALID_RECORD'},
            'INVALID_ORDER_RECEIPT': {'UNKNOWN_ORDER_LINE'},
            'INVALID_ORDER_STATUS': {'INVALID_STATUS'},
            'NEGATIVE_BALANCE': {'NEGATIVE_BALANCE', 'INSUFFICIENT_RESERVATION'},
        }
        self.assertTrue(aliases.get(code, {code}) & {x['code'] for x in report['errors']}, report)
        self.assertFalse(build.plan(self.root, build_count=2)['ok'])

    def test_acceptance_arithmetic_and_no_mutation(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        self.assertTrue(project.validate(self.root)['valid'])
        plan = build.plan(self.root, build_count=2)
        c, led = plan['parts']
        self.assertEqual([c[k] for k in ['physical','reserved','free','incoming','demand','spare_target','shortage_now','additional_to_order']], [3,1,2,2,2,1,1,0])
        self.assertEqual([led[k] for k in ['physical','reserved','free','demand','shortage_now','additional_to_order']], [6,2,4,4,0,0])
        self.assertTrue(plan['builds_ready_now'])
        self.assertFalse(plan['spare_targets_met_after_builds_now'])
        self.assertEqual(plan['workspace_revision'], 7)
        self.assertEqual(build.plan(self.root, build_count=2), plan)
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_unknown_is_not_verified_zero_even_with_events(self):
        self.edit_json('project.json', lambda p: p.update(stock_counts_verified=['led']))
        line = build.plan(self.root, build_count=2)['parts'][0]
        self.assertEqual(line['reserved'], 1)
        for key in ['physical','free','shortage_now','additional_to_order']:
            self.assertIsNone(line[key])
        self.assertIsNone(build.plan(self.root, build_count=2)['builds_ready_now'])
        self.assertIn('UNKNOWN_STOCK', [x['code'] for x in project.validate(self.root)['unknowns']])

    def test_verified_zero_and_spare_only_part(self):
        self.edit_rows('inventory-events.csv', lambda rows: rows.clear())
        result = build.plan(self.root, build_count=2)
        self.assertEqual(result['parts'][0]['physical'], 0)
        self.assertEqual(result['parts'][0]['shortage_now'], 3)
        self.assertEqual(result['parts'][0]['additional_to_order'], 1)
        self.assertFalse(result['builds_ready_now'])
        self.edit_rows('bom.csv', lambda rows: rows.pop())
        spare = build.plan(self.root, build_count=1, spare_targets={'led':3})['parts'][1]
        self.assertEqual((spare['demand'], spare['shortage_now']), (0,3))

    def test_partial_receipt_cancellation_and_status_not_stock(self):
        self.edit_rows('orders.csv', lambda rows: rows[0].update(quantity_ordered='4', quantity_cancelled='1', status='partially_received', expected_arrival='2000-01-01'))
        self.event(order_id='PO-1', source='order:PO-1/1')
        line = build.plan(self.root, build_count=2)['parts'][0]
        self.assertEqual((line['physical'], line['incoming']), (4,2))
        self.assertEqual(line['shortage_now'], 0)
        self.edit_rows('orders.csv', lambda rows: rows[0].update(quantity_cancelled='3',status='received'))
        line = build.plan(self.root, build_count=2)['parts'][0]
        self.assertEqual((line['physical'], line['incoming']), (4,0))

    def test_planned_order_does_not_count_as_incoming(self):
        self.edit_rows('orders.csv', lambda rows: rows[0].update(status='planned'))
        self.assertEqual(build.plan(self.root, build_count=2)['parts'][0]['additional_to_order'], 1)

    def test_incoming_does_not_make_build_ready(self):
        result = build.plan(self.root, build_count=3, spare_targets={})
        self.assertFalse(result['builds_ready_now'])
        self.assertEqual(result['parts'][0]['additional_to_order'], 0)

    def test_consumption_and_release_preserve_free_stock(self):
        self.event(event_type='consume', build_id='B-existing')
        line = build.plan(self.root, build_count=1)['parts'][0]
        self.assertEqual((line['physical'],line['reserved'],line['free']), (2,0,2))
        self.event(event_id='E6', event_type='release', part_id='led', quantity='1', build_id='B-existing')
        line = build.plan(self.root, build_count=1)['parts'][1]
        self.assertEqual((line['physical'],line['reserved'],line['free']), (6,1,5))

    def test_allocation_must_match_build_and_location(self):
        for overrides in [dict(location='other'), dict(quantity='2'), dict(build_id='other')]:
            with self.subTest(overrides=overrides):
                shutil.copyfile(FIXTURE/'inventory-events.csv', self.root/'inventory-events.csv')
                self.event(**({'event_type':'consume', 'build_id':'B-existing'} | overrides))
                self.assert_invalid('INVALID_RECORD' if 'build_id' in overrides else 'NEGATIVE_BALANCE')

    def test_consumption_cannot_use_another_declared_build_reservation(self):
        self.edit_json('builds.json', lambda b: b['builds'].append(
            dict(build_id='B-other', bom_revision='A', status='planned')))
        self.event(event_type='consume', build_id='B-other')
        before = {p.name:p.read_bytes() for p in self.root.iterdir()}
        self.assert_invalid('NEGATIVE_BALANCE')
        self.assertEqual(before, {p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_locations_cannot_borrow_stock_for_a_reservation(self):
        self.event(event_type='reserve', location='other', build_id='B-existing')
        self.assert_invalid('NEGATIVE_BALANCE')

    def test_adjustment_cannot_strand_reservations(self):
        self.event(event_type='adjustment_out', quantity='3', reason='damaged')
        self.assert_invalid('NEGATIVE_BALANCE')

    def test_negative_prefix_rejected_even_if_later_repaired(self):
        self.edit_rows('inventory-events.csv', lambda rows: rows.reverse())
        self.assert_invalid('NEGATIVE_BALANCE')

    def test_duplicate_ids_unknown_parts_and_bad_counts(self):
        cases = [
            ('bom.csv', lambda rows: rows.append(rows[0].copy()), 'DUPLICATE_ID'),
            ('inventory-events.csv', lambda rows: rows.append(rows[0].copy()), 'DUPLICATE_ID'),
            ('parts.csv', lambda rows: rows.append(rows[0].copy()), 'DUPLICATE_ID'),
            ('orders.csv', lambda rows: rows.append(rows[0].copy()), 'DUPLICATE_ID'),
            ('bom.csv', lambda rows: rows[0].update(part_id='Controller'), 'UNKNOWN_PART'),
        ]
        for value in ['-1','1.5','', 'True','0']:
            cases.append(('bom.csv', lambda rows, v=value: rows[0].update(quantity_per_build=v), 'INVALID_QUANTITY'))
        for name, edit, code in cases:
            with self.subTest(name=name, code=code):
                shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
                self.edit_rows(name, edit)
                self.assert_invalid(code)

    def test_receipt_integrity(self):
        for overrides, code in [(dict(quantity='3'), 'OVER_RECEIPT'), (dict(source='missing'), 'INVALID_ORDER_RECEIPT'), (dict(part_id='led'), 'INVALID_ORDER_RECEIPT')]:
            with self.subTest(overrides=overrides):
                shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
                self.event(**({'order_id':'PO-1', 'source':'order:PO-1/1'} | overrides))
                self.assert_invalid(code)

    def test_status_must_agree_with_ledger(self):
        self.edit_rows('orders.csv', lambda rows: rows[0].update(status='received'))
        self.assert_invalid('INVALID_ORDER_STATUS')

    def test_revision_selection_aggregates_repeated_parts(self):
        def revise(rows):
            rows.extend([dict(rows[0],bom_revision='B'), dict(rows[1],bom_revision='B',quantity_per_build='3'), dict(rows[1],bom_revision='B',line_id='3',quantity_per_build='1')])
        self.edit_rows('bom.csv', revise)
        self.assertEqual(build.plan(self.root, build_count=2, bom_revision='B')['parts'][1]['demand'], 8)
        self.assertEqual(build.plan(self.root, build_count=2)['parts'][1]['demand'], 4)
        self.edit_json('project.json', lambda p: p.update(project_id='unrelated-project'))
        self.assertEqual(build.plan(self.root, build_count=2)['parts'][1]['demand'], 4)

    def test_invalid_requests(self):
        for value in [True, -1, 1.5, '2']:
            with self.subTest(value=value):
                self.assertFalse(build.plan(self.root, build_count=value)['ok'])
        for targets in [{'controller':True}, {'missing':1}, {'led':-1}, []]:
            with self.subTest(targets=targets):
                self.assertFalse(build.plan(self.root, build_count=1, spare_targets=targets)['ok'])
        self.assertFalse(build.plan(self.root, build_count=1, bom_revision='missing')['ok'])

    def test_malformed_records_and_empty_template(self):
        self.assertTrue(project.validate('templates/project')['valid'])
        self.assertFalse(build.plan('templates/project', build_count=1)['ok'])
        (self.root/'project.json').write_text('{broken')
        self.assert_invalid('INVALID_RECORD')
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        (self.root/'parts.csv').write_text('wrong,header\nx,y\n')
        self.assert_invalid('INVALID_RECORD')
        (self.root/'parts.csv').unlink()
        self.assert_invalid('INVALID_RECORD')

    def test_event_quantities_evidence_and_timestamps(self):
        cases = [dict(quantity=v) for v in ['-1', '0', '1.5', '']]
        cases += [dict(timestamp='2026-01-01T00:00:00'), dict(source=''),
                  dict(event_type='unsupported'), dict(location=''), dict(operation_id=''),
                  dict(event_type='adjustment_in', reason='')]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
                self.event(**overrides)
                self.assert_invalid('INVALID_RECORD')

    def test_malformed_json_shapes(self):
        for name, value in [('project.json', []), ('builds.json', []),
                            ('builds.json', {'schema_version':'0.1-draft', 'builds':[{'build_id':[], 'bom_revision':'A', 'status':'planned'}]}),
                            ('builds.json', {'schema_version':'0.1-draft', 'builds':[{'build_id':'B', 'bom_revision':[], 'status':[]} ]})]:
            with self.subTest(name=name, value=value):
                shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
                (self.root/name).write_text(json.dumps(value))
                self.assert_invalid('INVALID_RECORD' if value == [] else ('INVALID_ID' if value['builds'][0]['build_id'] == [] else 'UNKNOWN_BOM'))

    def test_unknown_bom_and_json_boolean_counts(self):
        self.edit_json('project.json', lambda p: p.update(active_bom_revision='missing', workspace_revision=True))
        self.assert_invalid('INVALID_RECORD')
        shutil.copytree(FIXTURE, self.root, dirs_exist_ok=True)
        self.edit_json('project.json', lambda p: p.update(active_bom_revision='missing'))
        self.assert_invalid('UNKNOWN_BOM')


if __name__ == '__main__':
    unittest.main()
