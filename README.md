# backup-restore-verifier

Your backup job says SUCCESS every night. Your manifest file is intact. But has anyone actually **restored** the thing?

**backup-restore-verifier** proves your SQLite backup restores: it loads your `.db` file or `.sql` dump into a fresh temporary scratch database (your original is never touched), runs `PRAGMA integrity_check`, runs your smoke queries, and reports `RESTORE-OK` — or pinpoints exactly what broke. Exit code 1 on any failure, so it drops straight into a nightly cron or CI gate.

## 30-second quickstart

```bash
git clone https://github.com/Iceman2050/backup-restore-verifier.git
cd backup-restore-verifier
python3 backup_restore_verifier.py examples/good.db
```

With your own expectations in a tiny JSON config:

```bash
python3 backup_restore_verifier.py nightly-backup.db \
  --config '{"tables": {"users": {"min_rows": 1}, "orders": {"min_rows": 10}}, "allow_empty": ["audit_log"]}'
```

Defaults (no config): every table must be present and no table may be unexpectedly empty.

## Example output

Real captured runs — first a PASS:

```
$ python3 backup_restore_verifier.py examples/good.db
[backup-restore-verifier] source: examples/good.db
  restore:        OK (scratch copy: /tmp/backup_restore_verifier_qqcswd6g/scratch.db)
  integrity:      ok
  tables:         orders (2 rows), users (3 rows)
  smoke:          2 table(s), 5 row(s) total
VERDICT: RESTORE-OK
```

(Exit code: 0 — verified.)

Then a FAIL — a corrupted backup file:

```
$ python3 backup_restore_verifier.py examples/corrupt.db
[backup-restore-verifier] source: examples/corrupt.db
  restore:        OK (scratch copy: /tmp/backup_restore_verifier_33913qhz/scratch.db)
  integrity:      FAILED (DatabaseError: file is not a database)
VERDICT: CORRUPT — PRAGMA integrity_check failed: DatabaseError: file is not a database
```

(Exit code: 1 — verified.)

The scratch-copy paths are real temp dirs from the actual runs.

## Verdicts

| Verdict | Meaning | Exit |
|---|---|---|
| `RESTORE-OK` | Restored cleanly, integrity ok, all smoke queries passed | 0 |
| `LOAD-FAILED` | Backup file missing or unloadable | 1 |
| `CORRUPT` | `PRAGMA integrity_check` failed — corrupt pages, truncated file | 1 |
| `MISSING-TABLE` | An expected table isn't in the restored backup | 1 |
| `EMPTY-TABLE` | A table has fewer rows than expected (data silently lost) | 1 |

## What it does NOT do

- **SQLite only.** It verifies SQLite `.db` files and `.sql` dumps — not Postgres, MySQL, or filesystem backups.
- **It doesn't fix anything.** It proves the restore works or tells you exactly where it broke; repair is your job.
- **Smoke queries are shallow by design.** Table presence + row counts catch "the backup is garbage" — they don't validate business logic or data correctness.
- **It trusts your config.** If you say a table may be empty (`allow_empty`), it won't second-guess you.

## Tests

```bash
python3 -m unittest discover -s tests -v
```

12 tests, all green: a good `.db` and `.sql` dump pass with exact `RESTORE-OK` verdicts, a corrupt dump fails integrity, a dump missing an expected table fails smoke, an unexpectedly empty table fails smoke — plus a test proving the original file is never modified.

## Built by Ingenious AI

- [DisclosureGuard](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20DisclosureGuard.)
- [ModelMinder](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20ModelMinder.)
- [TermsWatch](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20TermsWatch.)
- [Vibe-Code Audit](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20Vibe-Code%20Audit.)
- [Rogue-Agent Defense](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20Rogue-Agent%20Defense.)
- [BreachHunter](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20BreachHunter.)
- [ChatBreaker](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20ChatBreaker.)
- [Agent Flight Recorder](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20Agent%20Flight%20Recorder.)
- [Agent Auth Gateway](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20Agent%20Auth%20Gateway.)
- [DomainGuard](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20DomainGuard.)
- [ContentCraft AI](https://wa.me/5016691053?text=Hi%20Ingenious%20AI%21%20I%20want%20early%20access%20to%20ContentCraft%20AI.)

Built with Muse — try it free: invite code 2HCQH1

## License

MIT — see [LICENSE](LICENSE).
