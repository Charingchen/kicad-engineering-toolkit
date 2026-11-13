"""Local POSIX transaction storage; readers never repair records implicitly."""
import base64
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import tempfile

STATE = '.inventory-state.json'
JOURNAL = '.inventory-journal.json'
LOCK = '.inventory.lock'
TARGETS = ('inventory-events.csv', 'orders.csv', 'project.json', STATE)


class TransactionError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def encode(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + '\n').encode()


def optional(path):
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def marker(root):
    if (root / JOURNAL).exists():
        raise TransactionError('RECOVERY_REQUIRED', 'Call inventory.recover before reading or writing records')
    return optional(root / STATE)


def state(raw, ledger):
    if raw is None:
        return {'version': 1, 'ledger_sha256': hashlib.sha256(ledger).hexdigest(), 'operations': {}}
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get('version') != 1
                or not isinstance(value.get('operations'), dict)
                or not isinstance(value.get('ledger_sha256'), str)):
            raise ValueError('unsupported metadata shape')
        for operation, entry in value['operations'].items():
            if (not operation.strip() or not isinstance(entry, dict)
                    or not isinstance(entry.get('events'), list)
                    or not isinstance(entry.get('result'), dict)
                    or entry['result'].get('ok') is not True):
                raise ValueError('invalid replay entry')
    except (ValueError, TypeError, AttributeError) as exc:
        raise TransactionError('INVALID_TRANSACTION_STATE', str(exc)) from exc
    if value['ledger_sha256'] != hashlib.sha256(ledger).hexdigest():
        raise TransactionError('HISTORY_CONFLICT', 'Ledger bytes differ from the last committed history')
    return value


@contextmanager
def locked(root):
    try:
        import fcntl
    except ImportError as exc:
        raise TransactionError('UNSUPPORTED_PLATFORM', 'Inventory writers require POSIX flock') from exc
    # Persistent file: unlinking it would permit concurrent locks on different inodes.
    with (root / LOCK).open('a+b') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise TransactionError('WORKSPACE_LOCKED', 'Another inventory writer holds the lock') from exc
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)


def sync_directory(root):
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def replace(root, name, content):
    fd, temporary = tempfile.mkstemp(prefix='.inventory-tmp-', dir=root)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, root / name)
        sync_directory(root)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def commit(root, before, after):
    journal = {'version': 1, 'files': {name: {
        'before': None if before[name] is None else base64.b64encode(before[name]).decode(),
        'after': base64.b64encode(after[name]).decode(),
    } for name in TARGETS}}
    replace(root, JOURNAL, encode(journal))
    finish(root, journal)


def finish(root, journal):
    try:
        if (not isinstance(journal, dict) or journal.get('version') != 1
                or not isinstance(journal.get('files'), dict)
                or set(journal['files']) != set(TARGETS)):
            raise ValueError('invalid transaction journal')
        decoded = {}
        for name in TARGETS:
            entry = journal['files'][name]
            old = None if entry['before'] is None else base64.b64decode(entry['before'], validate=True)
            new = base64.b64decode(entry['after'], validate=True)
            if optional(root / name) not in (old, new):
                raise TransactionError('RECOVERY_CONFLICT', f'Unexpected edits to {name}; journal retained')
            decoded[name] = new
    except (ValueError, TypeError, KeyError) as exc:
        raise TransactionError('INVALID_JOURNAL', str(exc)) from exc
    for name in TARGETS:
        replace(root, name, decoded[name])
    (root / JOURNAL).unlink()
    sync_directory(root)
