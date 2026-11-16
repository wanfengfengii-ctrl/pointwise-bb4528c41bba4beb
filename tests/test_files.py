import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import samples
from xbrl_local import Taxonomy, Instance, Warehouse


class FileTests(unittest.TestCase):
    def test_persistent_reopen_and_receipt(self):
        with tempfile.TemporaryDirectory(prefix='local-xbrl-') as directory:
            path = Path(directory) / 'facts.sqlite'
            tax = Taxonomy.from_file(samples.ROOT / 'examples' / 'taxonomy.xml')
            instance = Instance.from_file(samples.ROOT / 'examples' / 'accepted.xml')
            with Warehouse(path) as warehouse:
                receipt = warehouse.ingest('lab', 'initial', tax, instance)
                expected = warehouse.read('lab')
            with Warehouse(path) as warehouse:
                self.assertEqual(warehouse.read('lab'), expected)
                self.assertEqual(warehouse.receipts('lab'), [receipt])
                self.assertEqual(warehouse.ingest('lab', 'initial', tax, instance), receipt)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 1)

    def test_real_cli_import_reject_read_and_replay(self):
        with tempfile.TemporaryDirectory(prefix='local-xbrl-cli-') as directory:
            path = Path(directory) / 'cli.sqlite'
            def call(*args):
                result = subprocess.run([sys.executable, '-B', '-m', 'xbrl_local', '--db', str(path), *args],
                                        cwd=samples.ROOT, text=True, capture_output=True, timeout=30)
                self.assertEqual(result.stderr, '')
                return result.returncode, json.loads(result.stdout)
            args = ('import', '--dataset', 'lab', '--batch', 'initial', '--taxonomy',
                    str(samples.ROOT / 'examples' / 'taxonomy.xml'), '--instance',
                    str(samples.ROOT / 'examples' / 'accepted.xml'))
            status, receipt = call(*args)
            self.assertEqual(status, 0)
            self.assertEqual(receipt, {'dataset': 'lab', 'batch_id': 'initial', 'inserted': 9})
            self.assertEqual(call(*args), (status, receipt))
            status, before = call('read', '--dataset', 'lab')
            self.assertEqual(status, 0)
            self.assertEqual([r['id'] for r in before], list('abcdefghi'))
            rejected = list(args)
            rejected[4] = 'invalid'
            rejected[-1] = str(samples.ROOT / 'examples' / 'rejected.xml')
            status, error = call(*rejected)
            self.assertEqual(status, 2)
            self.assertIn('DIMENSION_QUALIFICATION', error['error'])
            self.assertEqual([i['fact_id'] for i in error['issues']],
                             ['bad-b', 'bad-ban', 'bad-hidden', 'bad-default', 'bad-extra', 'bad-missing'])
            self.assertEqual(call('read', '--dataset', 'lab'), (0, before))
            with Warehouse(path) as warehouse:
                self.assertEqual([r.batch_id for r in warehouse.receipts('lab')], ['initial'])

    def test_unknown_storage_version_is_not_overwritten(self):
        with tempfile.TemporaryDirectory(prefix='local-xbrl-version-') as directory:
            path = Path(directory) / 'unknown.sqlite'
            with sqlite3.connect(path) as db:
                db.execute('PRAGMA user_version=99')
            from xbrl_local import InputError
            with self.assertRaises(InputError):
                Warehouse(path)
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0], 99)
