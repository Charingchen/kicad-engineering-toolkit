# Inventory transactions

## Design and recovery contract

The writer supports a trusted, local POSIX filesystem with working `flock`,
atomic same-directory rename, file fsync and directory fsync. It does not promise
these semantics on network filesystems or Windows. Manual editors do not
participate in locking: keep the workspace quiescent while using these APIs.

A persistent `.inventory.lock` serializes cooperating writers using a nonblocking
exclusive advisory lock. Never unlink this file; locks belong to its inode.
Process exit releases the lock, including after an interrupted write.
Preview creates no workspace files and takes no lock.

Before writing records, the writer durably publishes `.inventory-journal.json`
with exact before/after bytes for the ledger, reconciled orders, project revision,
and `.inventory-state.json` replay/history metadata. Once this journal is durable,
the transaction is committed to roll forward. Each record is replaced atomically
and fsynced; metadata is replaced last. The journal is removed and the directory
fsynced only after all replacements are durable. Failure before journal publication
leaves records unchanged; failure afterwards requires explicit `inventory.recover`.

Toolkit readers refuse to report a usable validation or plan while a journal
exists. They also compare the state marker before/after reading and reject a
changed generation. Thus toolkit callers see a complete generation or an error,
never a usable partial transaction. External programs reading raw CSV/JSON may
observe intermediate files: multiple file renames are not physically atomic.

Recovery takes the writer lock and checks **all** participating records against
the journal's before/after bytes before changing anything. Unexpected edits or a
malformed journal fail closed for manual investigation. Otherwise recovery
idempotently installs the complete after image. There is no automatic stale-lock
delete, rollback, or automatic record mutation from a read-only API.

Replay metadata retains canonical event requests and their original success
results. Identical replay returns that result, even with the original expected
revision; different events under the same operation ID fail. Existing manually
entered operation IDs cannot be adopted as replay entries. After the first apply,
a ledger hash anchors all historical bytes; manual ledger edits, including manual
appends, fail closed. Git remains necessary to detect deletion or coordinated
rewriting of both history and its metadata. This is integrity checking, not a
security boundary or historical authentication system.

## Public API

```python
from kicad_engineering_toolkit import inventory, project

workspace = 'path/to/a/copied/synthetic/workspace'
current = project.validate(workspace)
request = dict(
    events=[dict(event_id='receipt-1', operation_id='receive-1',
                 timestamp='2026-10-29T00:00:00Z', event_type='receipt',
                 part_id='controller', quantity=1, location='drawer-A',
                 order_id='O-1', source='order:O-1/1')],
    expected_workspace_revision=current['workspace_revision'],
    expected_workspace_fingerprint=current['workspace_fingerprint'],
)
preview = inventory.record(workspace, **request)
# Inspect preview, including events and changed_records, before authorizing apply.
if preview['ok']:
    applied = inventory.record(workspace, **request, apply=True)
    assert applied == preview
```

`record` accepts one event, or two events forming a paired move under one operation
ID. Fields follow `inventory-events.csv`; omitted optional fields become empty
strings, integer quantities become decimal CSV strings. Event order is significant.
No existing rows can be edited or deleted through this API. It never creates
orders or builds, verifies stock counts, or changes pinned BOM revisions.

A receipt with `order_id` requires `source=order:<order_id>/<line_id>`; matching
order status is reconciled in the same transaction. Receiving a planned/unplaced
order is rejected. Quantity, evidence, build allocation, location, over-receipt,
and balance checks reuse `project.validate` on a full proposed generation.

Results contain `ok`, structured `errors`, the resulting revision/fingerprint,
events, changed records, reconciled order lines, warnings, and unknowns. A preview
and its successful apply return the same value; calling with `apply=True` is the
explicit mutation boundary. A successful preview alone does not mean a write
happened. Identical applied replay returns the original generation's result, not
a claim about the workspace's latest state. Call `project.validate` for that.
The existing seven-record fingerprint remains unchanged in definition; transaction
metadata is separately checked for stable generation and anchored ledger history.

After `RECOVERY_REQUIRED`, call `inventory.recover(workspace)` explicitly. A
successful result reports `recovered=True`; no journal reports `False`. Recovery
may itself be interrupted and resumed. A failed apply can be committed in the
journal even though it returned an I/O error: recover first, then retry the same
operation ID. Never submit a new ID merely because an apply response was lost.

Error codes include `REVISION_CONFLICT`, `OPERATION_CONFLICT`, `WORKSPACE_LOCKED`,
`RECOVERY_REQUIRED`, `RECOVERY_CONFLICT`, `HISTORY_CONFLICT`, `INVALID_JOURNAL`,
`INVALID_TRANSACTION_STATE`, `UNSUPPORTED_PLATFORM`, `IO_ERROR`, and existing
domain validation codes. An invalid apply can create the persistent lock file,
but changes no records. Preview, validation and planning never create it.

## Verification and limits

Run `PYTHONPATH=src python -m unittest discover -s tests -v`. Transaction tests use
only temporary copies of synthetic records. They include every durable replacement
boundary, a real subprocess exit while holding the lock, repeated interruption of
recovery, conflicting edits, cross-process contention, replay, receipts, moves,
consumption and unknown counts. Fault injection demonstrates process interruption,
not physical power-loss behavior of every filesystem or storage controller.

The metadata and journal are local bookkeeping, not a database or tamper-proof
audit log. Do not delete or edit them, use symlinked record files, run against an
untrusted directory, or combine manual edits with live operations. Back up the
whole workspace including hidden state. A crash may leave harmless
`.inventory-tmp-*` files; they are never authoritative and can be removed when no
writer is running. There is no implicit metadata reset or automatic historical
migration. Other record writers, build history, CLI, MCP and CAD remain deferred.
