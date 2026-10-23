import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PROJECT = Path(__file__).resolve().parents[1]


class DatabaseConfigurationTests(unittest.TestCase):
    def database_path_from_other_directory(self, database_url):
        environment = os.environ.copy()
        environment['PYTHONPATH'] = str(PROJECT)
        environment['DATABASE_URL'] = database_url
        with tempfile.TemporaryDirectory(prefix='fantasy-frc-cwd-') as directory:
            result = subprocess.run(
                [sys.executable, '-B', '-c', 'from src.database import engine; print(engine.url.database)'],
                cwd=directory, env=environment, check=True, capture_output=True, text=True,
            )
        return result.stdout.strip()

    def test_default_database_is_project_relative_from_other_working_directory(self):
        actual = Path(self.database_path_from_other_directory('')).resolve()
        self.assertEqual(actual, (PROJECT / 'fantasy_frc.db').resolve())

    def test_explicit_database_configuration_is_preserved(self):
        self.assertEqual(self.database_path_from_other_directory('sqlite:///:memory:'), ':memory:')


if __name__ == '__main__':
    unittest.main()
