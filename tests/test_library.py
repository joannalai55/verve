import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/verve-english-coach/scripts/verve_library.py'


class LibraryTest(unittest.TestCase):
    def test_capture_recall_and_persistence(self):
        with tempfile.TemporaryDirectory() as directory:
            def run(*args):
                result = subprocess.run([sys.executable, str(SCRIPT), '--data-dir', directory, *args], check=True, capture_output=True, text=True)
                return json.loads(result.stdout)
            self.assertTrue(run('init')['created'])
            item = run('add', '--kind', 'phrase', '--text', 'get to the heart of it', '--tags', 'work')['item']
            self.assertEqual(run('due')[0]['id'], item['id'])
            duplicate = run('add', '--kind', 'phrase', '--text', 'Get to the heart of it', '--meaning', 'identify the central issue')
            self.assertFalse(duplicate['created'])
            self.assertEqual(len(run('search', 'central issue')), 1)
            reviewed = run('review', '--id', item['id'], '--score', '3')
            self.assertEqual(reviewed['review']['interval_days'], 7)
            self.assertEqual(run('due'), [])
            self.assertEqual(run('stats')['total'], 1)
            run('profile', 'set', '--key', 'tone', '--value', 'direct')
            self.assertEqual(run('profile', 'show')['tone'], 'direct')
            self.assertFalse(run('init')['created'])
            self.assertEqual(run('stats')['total'], 1)

    def test_invalid_score_leaves_library_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            base = [sys.executable, str(SCRIPT), '--data-dir', directory]
            subprocess.run(base + ['init'], check=True, capture_output=True)
            before = (Path(directory) / 'library.json').read_bytes()
            result = subprocess.run(base + ['review', '--id', 'missing', '--score', '9'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((Path(directory) / 'library.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
