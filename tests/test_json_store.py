import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from json_store import read_json, write_json


class JsonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / '校正 結果.json'
        write_json(self.path, dict(sequence=0, message='原設定'))

    def test_reader_releases_file_before_parsing_its_snapshot(self):
        loads = json.loads
        def parse(payload):
            write_json(self.path, dict(sequence=1, message='校正完成'))
            return loads(payload)
        with patch('json_store.json.loads', side_effect=parse):
            self.assertEqual(read_json(self.path)['sequence'], 0)
        self.assertEqual(read_json(self.path), dict(sequence=1, message='校正完成'))

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_temporary_nonsharing_reader_is_retried(self):
        reader = self.path.open('r', encoding='utf-8')
        self.addCleanup(reader.close)
        def release():
            time.sleep(.06)
            reader.close()
        thread = threading.Thread(target=release)
        thread.start()
        try:
            write_json(self.path, dict(sequence=1))
        finally:
            thread.join()
        self.assertEqual(read_json(self.path), dict(sequence=1))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing semantics')
    def test_persistent_lock_preserves_original_and_cleans_own_temporary(self):
        with self.path.open('r', encoding='utf-8') as reader:
            with self.assertRaises(PermissionError):
                write_json(self.path, dict(sequence=1), retry_timeout=.03)
            self.assertEqual(json.load(reader)['sequence'], 0)
        self.assertEqual(read_json(self.path)['sequence'], 0)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_concurrent_readers_and_writers_only_observe_complete_snapshots(self):
        def writer(worker):
            for sequence in range(60):
                write_json(self.path, dict(sequence=sequence, message='完整資料' * 100, worker=worker))
        def reader():
            for _ in range(200):
                value = read_json(self.path)
                self.assertIn('sequence', value)
                if 'worker' in value:
                    self.assertEqual(value['message'], '完整資料' * 100)
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(writer, worker) for worker in range(2)]
            futures += [pool.submit(reader) for _ in range(3)]
            for future in futures:
                future.result(timeout=15)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])

    def test_invalid_json_number_does_not_modify_previous_file(self):
        with self.assertRaises(ValueError):
            write_json(self.path, dict(delay=float('nan')))
        self.assertEqual(read_json(self.path)['sequence'], 0)
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
