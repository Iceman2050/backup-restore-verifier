"""Tests for backup-restore-verifier: exact verdicts on real fixtures."""

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest

import backup_restore_verifier as v


class VerifierCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="brv_tests_")

        # Good database: two populated tables.
        cls.good_db = os.path.join(cls.dir, "good.db")
        conn = sqlite3.connect(cls.good_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total REAL)")
        conn.executemany("INSERT INTO users (name) VALUES (?)",
                         [("alice",), ("bob",), ("carol",)])
        conn.executemany("INSERT INTO orders (total) VALUES (?)", [(9.99,), (19.5,)])
        conn.commit()
        conn.close()

        # Good .sql dump of the same database.
        cls.good_sql = os.path.join(cls.dir, "good.sql")
        conn = sqlite3.connect(cls.good_db)
        with open(cls.good_sql, "w", encoding="utf-8") as fh:
            for line in conn.iterdump():
                fh.write(line + "\n")
        conn.close()

        # Corrupt database: random bytes, not a database at all.
        cls.corrupt_db = os.path.join(cls.dir, "corrupt.db")
        with open(cls.corrupt_db, "wb") as fh:
            fh.write(os.urandom(4096))

        # Truncated dump: valid SQL cut off mid-statement.
        cls.truncated_sql = os.path.join(cls.dir, "truncated.sql")
        with open(cls.good_sql, "r", encoding="utf-8") as fh:
            full = fh.read()
        with open(cls.truncated_sql, "w", encoding="utf-8") as fh:
            fh.write(full[: len(full) // 3])

        # Database missing an expected table.
        cls.missing_db = os.path.join(cls.dir, "missing_table.db")
        conn = sqlite3.connect(cls.missing_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO users (name) VALUES ('alice')")
        conn.commit()
        conn.close()

        # Database with an unexpectedly empty table.
        cls.empty_db = os.path.join(cls.dir, "empty_table.db")
        conn = sqlite3.connect(cls.empty_db)
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, total REAL)")
        conn.execute("INSERT INTO orders (total) VALUES (9.99)")
        conn.commit()
        conn.close()

        # Config expecting both tables to hold data.
        cls.config = os.path.join(cls.dir, "config.json")
        with open(cls.config, "w", encoding="utf-8") as fh:
            json.dump({"tables": {"users": {"min_rows": 1},
                                   "orders": {"min_rows": 1}},
                       "allow_empty": []}, fh)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.dir, ignore_errors=True)

    def sha(self, path):
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()


class TestGoodBackups(VerifierCase):
    def test_good_db_passes(self):
        verdict, report = v.verify(self.good_db, self.config)
        self.assertEqual(verdict, "RESTORE-OK", "\n".join(report))

    def test_good_sql_dump_passes(self):
        verdict, report = v.verify(self.good_sql, self.config)
        self.assertEqual(verdict, "RESTORE-OK", "\n".join(report))

    def test_good_db_passes_with_default_config(self):
        verdict, report = v.verify(self.good_db)
        self.assertEqual(verdict, "RESTORE-OK", "\n".join(report))

    def test_original_file_is_never_touched(self):
        before = self.sha(self.good_db)
        v.verify(self.good_db, self.config)
        self.assertEqual(self.sha(self.good_db), before)

    def test_main_returns_exit_code_0(self):
        self.assertEqual(v.main([self.good_db, "--config", self.config]), 0)


class TestBadBackups(VerifierCase):
    def test_corrupt_db_fails_integrity(self):
        verdict, report = v.verify(self.corrupt_db, self.config)
        self.assertEqual(verdict, "CORRUPT", "\n".join(report))
        self.assertTrue(any("integrity" in line for line in report))

    def test_truncated_sql_dump_fails(self):
        verdict, report = v.verify(self.truncated_sql, self.config)
        self.assertNotEqual(verdict, "RESTORE-OK", "\n".join(report))
        self.assertIn(verdict, ("LOAD-FAILED", "CORRUPT", "MISSING-TABLE", "EMPTY-TABLE"))

    def test_missing_table_fails_smoke(self):
        verdict, report = v.verify(self.missing_db, self.config)
        self.assertEqual(verdict, "MISSING-TABLE", "\n".join(report))
        self.assertTrue(any("orders" in line for line in report))

    def test_empty_table_fails_smoke(self):
        verdict, report = v.verify(self.empty_db, self.config)
        self.assertEqual(verdict, "EMPTY-TABLE", "\n".join(report))

    def test_allow_empty_config_permits_empty_table(self):
        cfg = os.path.join(self.dir, "allow_empty.json")
        with open(cfg, "w", encoding="utf-8") as fh:
            json.dump({"tables": {}, "allow_empty": ["users"]}, fh)
        verdict, report = v.verify(self.empty_db, cfg)
        self.assertEqual(verdict, "RESTORE-OK", "\n".join(report))

    def test_missing_file_is_load_failed(self):
        verdict, report = v.verify(os.path.join(self.dir, "nope.db"))
        self.assertEqual(verdict, "LOAD-FAILED")

    def test_main_returns_exit_code_1_on_failure(self):
        self.assertEqual(v.main([self.corrupt_db]), 1)
        self.assertEqual(v.main([self.missing_db, "--config", self.config]), 1)


if __name__ == "__main__":
    unittest.main()
