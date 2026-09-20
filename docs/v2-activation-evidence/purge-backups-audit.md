# `backend/data/purge_backups/` — read-only audit

**Nothing was deleted, moved, chmod'd or committed.** The files were opened for
reading and aggregated. No personal data appears anywhere in this document:
counts, categories and domain classes only, never a name, email address, phone
number, CNIC, case detail or hash value.

Audited 2026-09-05. Two files, both from 2026-09-01, holding **27 user records
in total** — 24 in the fixture purge and 3 in the test-accounts file — of which
23 carry a `password_hash`.

---

## Why this is in the activation pack at all

The pack's §1 inventory listed these files while looking for a migration
target, and rejected them — one holds a single already-deleted fixture
document, which is not an estate. But looking at them established that
**production-shaped user records, including password hashes, are sitting in
the working tree in plaintext with no retention rule.** That is unrelated to
the migration and more urgent than it, so it is written up separately here
rather than buried in a rejection table.

---

## Inventory

| File | Size | Written | Mode |
|---|---:|---|---|
| `fixture_purge_20260901T043032Z.json` | 218,451 B | 2026-09-01 04:30 UTC | `0o666` |
| `attorney_ai_test_accounts_20260901T075551Z.json` | 2,564 B | 2026-09-01 07:55 UTC | `0o666` |

`0o666` is Python's `os.stat` view. On Windows the real gate is the NTFS ACL,
which this reports nothing about — treat the mode as "not restricted by the
writing process", not as a measured permission. Neither file is chmod'd or
ACL'd by the script that creates it; both inherit whatever the directory grants.

---

## `fixture_purge_20260901T043032Z.json`

A record of a fixture-account purge against database `attorney_ai` — the
**production** database.

| Category | Count |
|---|---:|
| User records | 24 |
| ├ with an `@example.*` address | 23 |
| ├ with a blank address | 1 |
| └ carrying a `password_hash` | 23 |
| `cases` | 7 |
| `engagements` | 9 |
| `appointments` | 1 |
| `documents` | 1 |
| `notifications` | 14 |
| `kept_because_real_counterparty` | 0 (empty) |

### Sensitivity

**Moderate, not negligible.** The mitigating facts are real: 23 of 24 addresses
are `@example.*` reserved-domain fixtures, and `kept_because_real_counterparty`
is empty, meaning the purge found no real user entangled with these accounts.
This is very probably synthetic data throughout.

The aggravating facts are also real:

- **23 records carry `password_hash`.** Even a fixture hash is a credential
  artefact. If any fixture password was reused anywhere real, this is a
  credential file.
- **One record has a blank address**, so it cannot be shown to be a fixture by
  the same argument as the other 23. One unclassifiable record in a file of 24
  is enough to stop calling the file "definitely all synthetic".
- **The dependent records were copied whole** — 7 cases, 9 engagements, 14
  notifications — with whatever free text they contained. Cases and
  notifications in this system carry client narrative.
- It was taken against **production**, so its provenance is production
  regardless of the content's origin.

**Treat it as data requiring protection.** Not because it is proven to hold real
personal data, but because nothing in the file proves it does not, and the cost
of being wrong is a credential-and-narrative leak.

---

## `attorney_ai_test_accounts_20260901T075551Z.json`

2,564 bytes; a JSON list of **3** user records. Same shape, same concerns, two
orders of magnitude smaller.

**No script in the repository writes this filename.** `grep -rl` across
`backend/scripts/` and `backend/app/` for `attorney_ai_test_accounts` and
`test_accounts_` returns nothing. It was produced by an ad-hoc command or a
script that no longer exists, so its provenance cannot be reconstructed from the
tree — which is itself part of the finding.

---

## Which script creates them

[`backend/scripts/purge_test_fixtures.py`](../../backend/scripts/purge_test_fixtures.py):

```python
backup_dir = BACKEND / "data" / "purge_backups"      # :176
backup_dir.mkdir(parents=True, exist_ok=True)        # :177
backup_path = backup_dir / f"fixture_purge_{stamp}.json"   # :178
...
backup_path.write_text(json.dumps(payload, indent=2, default=_json_default),
                       encoding="utf-8")             # :189
print(f"\nbackup written: {backup_path}")            # :190
...
res = await db[coll].delete_many({"_id": {"$in": [...]}})  # :195
res = await db["users"].delete_many({"_id": {"$in": list(doomed_ids)}})  # :198
```

The design is sound in intent: write the record **before** deleting, so a
mistaken purge is recoverable. The gap is everything after the write.

---

## Encryption, access control, retention

| Control | Present | Detail |
|---|:--:|---|
| Encryption at rest | **No** | `write_text(json.dumps(...), encoding="utf-8")` — plaintext JSON |
| Encryption in transit | n/a | Written to local disk |
| Access control | **No** | No `chmod`, no ACL, no `0o600`; inherits the directory |
| Retention policy | **No** | No age limit, no rotation, no cap on file count |
| Deletion path | **No** | Nothing in the repository ever removes one |
| Restore path | **No** | No script reads these files back; recovery would be hand-written |
| Audit of access | **No** | Nothing records who read one |
| Version control | **Excluded** | `.gitignore:124`; `git ls-files` returns 0 — **not** in history |

The `.gitignore` exclusion is the one control that exists, and it is the one
that matters most, because it is what keeps these out of a public repository.
**It must not be removed.** Note what it does *not* do: the files still sit in
the working tree, on a laptop, indefinitely, readable by anything running as
this user — including a backup agent or a cloud-sync client.

The restore gap deserves its own line. The stated purpose of these files is
recoverability, and no code can restore one. Their protective value today is
"a human could reconstruct the deletion by hand from the JSON" — which is worth
something, but far less than the risk of holding password hashes forever.

---

## Proposed handling

**Nothing below was executed. Every item needs your decision first.**

### Retention

**90 days from the purge date, then deletion.** Rationale: a purge that was a
mistake is discovered within days, not months. Both current files are 4 days
old, so nothing is due.

The safe order is:

1. **Confirm the deletions were intended** — for the 24-record file, that means
   confirming those accounts were meant to go. If yes, its recovery value is
   already spent and it is pure liability.
2. **Restrict permissions now**, before anything else. `0o600` on both files and
   on the directory (on Windows, an ACL granting only the owning account).
3. **Decide on the 3-account file**, whose provenance cannot be established. My
   recommendation is deletion — an unidentifiable credential file with no known
   writer has no defensible retention argument.
4. **Delete on the schedule**, not opportunistically.

### Changes to `purge_test_fixtures.py`

Proposed, **not implemented** — the brief stops at documentation:

1. `os.chmod(backup_path, 0o600)` immediately after `write_text`, before the
   `print`.
2. Redact `password_hash` from the payload. It has no recovery value: a restore
   would reset credentials anyway, and a purge record is not the right place to
   preserve one.
3. Write an `expires_at` field into the payload so retention is self-describing
   rather than a rule in a document.
4. Prune backups older than the retention window at the start of each run, so
   the directory cannot grow unbounded and unattended.
5. Add a `restore_from_backup` counterpart, or stop describing the file as a
   backup. Right now the name promises a capability that does not exist.

### Deletion, when it happens

Ordinary file deletion is adequate here — these are not classified records, and
secure-erase theatre on a laptop SSD with wear levelling does not deliver what
it appears to. Delete the file, record that it was deleted and why. **Do not
delete anything until item 1 above is confirmed.**

---

## Relation to the migration

**None, technically.** These files are not a migration target, do not affect
`dry_run()`, and are not read by `document_migration`.

They matter to activation for one reason: the migration will relabel documents
and write revisions in the same production database that this purge deleted from.
Anyone with read access to this working tree already holds 23 password hashes
and 7 cases' worth of narrative from it. That is worth closing before adding
another operation to the same database — not because the migration makes it
worse, but because it is cheap to fix now and it is the kind of thing that gets
forgotten once a bigger change lands on top of it.
