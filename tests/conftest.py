"""Pytest hooks.

PySide6 6.12 on Python 3.10 can abort in Qt's interpreter-shutdown teardown
after every test has already passed (``munmap_chunk(): invalid pointer``).
Exit directly once the session succeeded; failures still use pytest's normal
exit path.
"""

from __future__ import annotations

import os
import sys


def pytest_sessionfinish(session, exitstatus):
    if exitstatus == 0:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
