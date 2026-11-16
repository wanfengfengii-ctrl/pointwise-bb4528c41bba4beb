"""Run the complete original deterministic regression suite."""
from pathlib import Path
import sys
import unittest

if __name__ == '__main__':
    if sys.version_info < (3, 11):
        raise SystemExit('Python 3.11 or newer is required')
    suite = unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parent / 'tests'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(0 if result.wasSuccessful() else 1)
