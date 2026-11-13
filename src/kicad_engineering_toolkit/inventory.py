"""Preview and explicitly apply inventory events in trusted local workspaces."""
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile

from . import project, _transactions as tx


def _failure(code, message, errors=None):
    return {'ok': False, 'errors': errors or [
        {'code': code, 'record': 'inventory.record', 'message': message}]}


def _csv(raw):
    return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline='')))


def _serialize(rows, fields, header=True):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    if header:
        writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode()


def _fingerprint(files):
    digest = hashlib.sha256()
    for name in project.FILES:
        digest.update(name.encode() + b'\0' + files[name] + b'\0')
    return digest.hexdigest()


def _events(events):
    fields = project.HEADERS['inventory-events.csv'].split(',')
    if not isinstance(events, list) or not 1 <= len(events) <= 2:
        raise tx.TransactionError('INVALID_REQUEST', 'Provide one event or a paired move')
    normalized = []
    for event in events:
        if not isinstance(event, dict) or set(event) - set(fields):
            raise tx.TransactionError('INVALID_REQUEST', 'Event fields must match the inventory contract')
        row = {field: event.get(field, '') for field in fields}
        if type(row['quantity']) is int:
            row['quantity'] = str(row['quantity'])
        if any(not isinstance(value, str) for value in row.values()):
            raise tx.TransactionError('INVALID_REQUEST', 'Event values must be strings or integer quantities')
        if not row['operation_id'].strip():
            raise tx.TransactionError('MISSING_ID', 'operation_id is required')
        normalized.append(row)
    if len({row['operation_id'] for row in normalized}) != 1:
        raise tx.TransactionError('INVALID_REQUEST', 'One transaction requires one operation_id')
    return normalized


def _prepare(root, events, revision, fingerprint):
    generation = tx.marker(root)
    files = {name: (root / name).read_bytes() for name in project.FILES}
    metadata = tx.state(generation, files['inventory-events.csv'])
    if tx.marker(root) != generation:
        raise tx.TransactionError('REVISION_CONFLICT', 'Workspace changed while reading')
    operation = events[0]['operation_id']
    previous = metadata['operations'].get(operation)
    if previous is not None:
        if previous['events'] != events:
            raise tx.TransactionError('OPERATION_CONFLICT', 'operation_id already has different content')
        return previous['result'], None
    if (type(revision) is not int or not isinstance(fingerprint, str)
            or len(fingerprint) != 64):
        raise tx.TransactionError('INVALID_REQUEST', 'Expected integer revision and SHA-256 fingerprint are required')
    validation = project.validate(root)
    if not validation['valid']:
        return _failure('INVALID_RECORD', 'Workspace is invalid', validation['errors']), None
    if (_fingerprint(files) != validation['workspace_fingerprint']
            or tx.marker(root) != generation
            or revision != validation['workspace_revision']
            or fingerprint != validation['workspace_fingerprint']):
        raise tx.TransactionError('REVISION_CONFLICT', 'Preview a fresh workspace revision and fingerprint')
    persisted = _csv(files['inventory-events.csv'])
    if any(row['operation_id'] == operation for row in persisted):
        raise tx.TransactionError('OPERATION_CONFLICT', 'Existing manual operation has no replay receipt')
    # Append only: never rewrite any historical ledger byte.
    ledger = files['inventory-events.csv']
    separator = b'' if ledger.endswith(b'\n') else b'\n'
    proposed = dict(files)
    proposed['inventory-events.csv'] = ledger + separator + _serialize(
        events, project.HEADERS['inventory-events.csv'].split(','), header=False)
    orders = _csv(files['orders.csv'])
    touched = set()
    for event in events:
        if event['event_type'] != 'receipt' or not event['order_id']:
            continue
        for order in orders:
            ref = f"order:{order['order_id']}/{order['line_id']}"
            if event['order_id'] == order['order_id'] and event['source'] == ref:
                if order['status'] == 'planned':
                    raise tx.TransactionError('INVALID_STATUS', 'Cannot receive an unplaced planned order')
                received = sum(project._integer(row['quantity'], 1) or 0
                               for row in persisted + events
                               if row['event_type'] == 'receipt' and row['order_id'] == order['order_id']
                               and row['source'] == ref)
                outstanding = int(order['quantity_ordered']) - int(order['quantity_cancelled']) - received
                order['status'] = 'received' if outstanding == 0 else 'partially_received'
                touched.add(ref)
    if touched:
        proposed['orders.csv'] = _serialize(orders, project.HEADERS['orders.csv'].split(','))
    p = json.loads(files['project.json'])
    p['workspace_revision'] += 1
    proposed['project.json'] = tx.encode(p)
    # Reuse all domain checks on the complete proposed generation outside the workspace.
    with tempfile.TemporaryDirectory() as temporary:
        candidate = Path(temporary)
        for name, content in proposed.items():
            (candidate / name).write_bytes(content)
        check = project.validate(candidate)
    if not check['valid']:
        return _failure('INVALID_EVENT', 'Proposed records are invalid', check['errors']), None
    result = {'ok': True, 'operation_id': operation, 'workspace_revision': p['workspace_revision'],
              'workspace_fingerprint': _fingerprint(proposed), 'errors': [],
              'input_records': list(project.FILES), 'unknowns': check['unknowns'],
              'warnings': check['warnings'], 'events': events,
              'assumptions': check['assumptions'] + ['Trusted local POSIX filesystem; no concurrent manual edits.'],
              'supported_checks': check['supported_checks'] + ['revision/fingerprint checks', 'immutable ledger and operation replay'],
              'changed_records': [name for name in project.FILES if files[name] != proposed[name]],
              'reconciled_order_lines': sorted(touched)}
    metadata['ledger_sha256'] = hashlib.sha256(proposed['inventory-events.csv']).hexdigest()
    metadata['operations'][operation] = {'events': events, 'result': result}
    before = {name: files[name] for name in tx.TARGETS if name != tx.STATE}
    before[tx.STATE] = generation
    after = {name: proposed[name] for name in tx.TARGETS if name != tx.STATE}
    after[tx.STATE] = tx.encode(metadata)
    return result, (before, after)


def record(workspace, *, events, expected_workspace_revision,
           expected_workspace_fingerprint, apply=False):
    """Preview by default; apply=True explicitly authorizes the same checked request.

    Expected revision/fingerprint come from project.validate. A successful result
    describes the resulting generation, even during preview. Identical applied
    replay returns the original result without another revision increment.
    """
    root = Path(workspace)
    try:
        if type(apply) is not bool:
            raise tx.TransactionError('INVALID_REQUEST', 'apply must be a boolean')
        normalized = _events(events)
        if not apply:
            return _prepare(root, normalized, expected_workspace_revision,
                            expected_workspace_fingerprint)[0]
        with tx.locked(root):
            result, transaction = _prepare(root, normalized, expected_workspace_revision,
                                           expected_workspace_fingerprint)
            if transaction is not None:
                before, after = transaction
                # Recheck just before publishing; manual concurrent edits remain unsupported.
                if any(tx.optional(root / name) != content for name, content in before.items()):
                    raise tx.TransactionError('REVISION_CONFLICT', 'Records changed before apply')
                tx.commit(root, before, after)
            return result
    except tx.TransactionError as exc:
        return _failure(exc.code, exc.message)
    except (OSError, UnicodeError, ValueError, csv.Error) as exc:
        return _failure('IO_ERROR', str(exc))


def recover(workspace):
    """Explicitly finish a journaled transaction; never called by read-only APIs."""
    root = Path(workspace)
    try:
        with tx.locked(root):
            raw = tx.optional(root / tx.JOURNAL)
            if raw is None:
                return {'ok': True, 'recovered': False, 'errors': []}
            try:
                journal = json.loads(raw)
            except ValueError as exc:
                raise tx.TransactionError('INVALID_JOURNAL', str(exc)) from exc
            tx.finish(root, journal)
            return {'ok': True, 'recovered': True, 'errors': []}
    except tx.TransactionError as exc:
        return _failure(exc.code, exc.message)
    except OSError as exc:
        return _failure('IO_ERROR', str(exc))
