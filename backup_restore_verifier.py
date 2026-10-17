#!/usr/bin/env python3
"""backup-restore-verifier — PROVE your backup actually restores.

Most "backup checkers" only verify a manifest file exists. This tool does the
thing that actually matters: it restores your SQLite database (or .sql dump)
into a fresh temporary scratch database — never touching the original — then:

  1. runs PRAGMA integrity_check (catches corrupt pages / truncated files),
  2. runs smoke queries from a tiny JSON config (or sensible defaults:
     every table is present, no table is unexpectedly empty),
  3. reports RESTORE-OK, or pinpoints the failure.

Exit code 0 on success, 1 on any failure: drop it in a nightly cron or CI gate.

Stdlib only: sqlite3, tempfile, argparse, unittest.
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile

VERDICT_OK = "RESTORE-OK"
VERDICT_LOAD_FAILED = "LOAD-FAILED"
VERDICT_CORRUPT = "CORRUPT"
VERDICT_MISSING_TABLE = "MISSING-TABLE"
VERDICT_EMPTY_TABLE = "EMPTY-TABLE"


def restore_to_scratch(source):
    """Restore source into a fresh temp dir. Returns (tmpdir, db_path).

    Copies a .db file or executes a .sql dump. The original is only ever read.
    """
    if not os.path.isfile(source):
        raise FileNotFoundError("no such file: %s" % source)
    tmpdir = tempfile.mkdtemp(prefix="backup_restore_verifier_")
    db_path = os.path.join(tmpdir, "scratch.db")
    try:
        if source.lower().endswith(".sql"):
            conn = sqlite3.connect(db_path)
            try:
                with open(source, "r", encoding="utf-8") as fh:
                    conn.executescript(fh.read())
                conn.commit()
            finally:
                conn.close()
        else:
            shutil.copy2(source, db_path)
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise
    return tmpdir, db_path


def check_integrity(db_path):
    """Run PRAGMA integrity_check. Returns (ok, detail)."""
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute("PRAGMA integrity_check").fetchall()
    finally:
        conn.close()
    texts = [r[0] for r in rows]
    if texts == ["ok"]:
        return True, "ok"
    return False, "; ".join(texts)


def list_user_tables(db_path):
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


def table_row_count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute('SELECT COUNT(*) FROM "%s"' % table).fetchone()[0]
    finally:
        conn.close()


def load_config(path):
    """Config: {"tables": {"users": {"min_rows": 1}}, "allow_empty": ["audit"]}.

    Defaults when no config is given: every table present, min_rows=1.
    """
    if not path:
        return {"tables": {}, "allow_empty": []}
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    cfg.setdefault("tables", {})
    cfg.setdefault("allow_empty", [])
    return cfg


def smoke_check(db_path, config):
    """Returns (failures, table_summaries).

    failures: list of (verdict, message). table_summaries: [(name, rows)].
    """
    failures = []
    tables = list_user_tables(db_path)
    expected = config.get("tables", {})
    allow_empty = set(config.get("allow_empty", []))

    for name in expected:
        if name not in tables:
            failures.append(
                (VERDICT_MISSING_TABLE,
                 "expected table '%s' not found in restored backup" % name)
            )

    summaries = []
    for name in tables:
        rows = table_row_count(db_path, name)
        summaries.append((name, rows))
        if name in allow_empty:
            continue
        min_rows = expected.get(name, {}).get("min_rows", 1)
        if rows < min_rows:
            failures.append(
                (VERDICT_EMPTY_TABLE,
                 "table '%s' has %d row(s), expected at least %d"
                 % (name, rows, min_rows))
            )
    return failures, summaries


def verify(source, config_path=None):
    """Full pipeline. Returns (verdict, report_lines)."""
    lines = ["[backup-restore-verifier] source: %s" % source]

    try:
        tmpdir, db_path = restore_to_scratch(source)
    except FileNotFoundError as exc:
        lines.append("  restore:        FAILED (%s)" % exc)
        lines.append("VERDICT: %s — could not read the backup file" % VERDICT_LOAD_FAILED)
        return VERDICT_LOAD_FAILED, lines
    except (sqlite3.Error, OSError, UnicodeDecodeError) as exc:
        lines.append("  restore:        FAILED (%s: %s)" % (type(exc).__name__, exc))
        lines.append("VERDICT: %s — the backup could not be loaded: %s"
                     % (VERDICT_LOAD_FAILED, exc))
        return VERDICT_LOAD_FAILED, lines

    lines.append("  restore:        OK (scratch copy: %s)" % db_path)

    try:
        ok, detail = check_integrity(db_path)
    except sqlite3.Error as exc:
        ok, detail = False, "%s: %s" % (type(exc).__name__, exc)
    if not ok:
        lines.append("  integrity:      FAILED (%s)" % detail)
        lines.append("VERDICT: %s — PRAGMA integrity_check failed: %s"
                     % (VERDICT_CORRUPT, detail))
        return VERDICT_CORRUPT, lines
    lines.append("  integrity:      ok")

    try:
        config = load_config(config_path)
    except (OSError, ValueError) as exc:
        lines.append("VERDICT: %s — could not read config: %s"
                     % (VERDICT_LOAD_FAILED, exc))
        return VERDICT_LOAD_FAILED, lines

    failures, summaries = smoke_check(db_path, config)
    total_rows = sum(n for _, n in summaries)
    lines.append("  tables:         %s" % (
        ", ".join("%s (%d rows)" % (name, n) for name, n in summaries)
        or "(no tables)"))
    lines.append("  smoke:          %d table(s), %d row(s) total"
                 % (len(summaries), total_rows))

    if failures:
        verdict, message = failures[0]
        lines.append("VERDICT: %s — %s" % (verdict, message))
        return verdict, lines

    lines.append("VERDICT: RESTORE-OK")
    return VERDICT_OK, lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Prove a SQLite backup actually restores: load it into a "
                    "scratch database, run integrity_check, run smoke queries."
    )
    parser.add_argument("source", help="SQLite .db file or .sql dump to verify")
    parser.add_argument("--config", default=None,
                        help="JSON config: expected tables and min rows "
                             '(e.g. {"tables": {"users": {"min_rows": 1}}, '
                             '"allow_empty": ["audit_log"]})')
    args = parser.parse_args(argv)

    verdict, lines = verify(args.source, args.config)
    print("\n".join(lines))
    return 0 if verdict == VERDICT_OK else 1


if __name__ == "__main__":
    sys.exit(main())
