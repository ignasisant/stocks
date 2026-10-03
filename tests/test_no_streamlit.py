"""The app runs without Streamlit installed.

Streamlit was the first front end and is gone, and it is not a dependency any
more. A module that still imported it would pass every other test on a machine
where the package happens to be around — a stale virtualenv, a tool that pulls
it in — and fail on the deploy, which installs from the lock. So every module
under `stocks` is imported in a fresh interpreter in which `import streamlit`
cannot succeed.
"""

import subprocess
import sys

SCRIPT = """
import importlib
import pkgutil
import sys

sys.modules["streamlit"] = None  # every `import streamlit` now raises

import stocks

for info in pkgutil.walk_packages(stocks.__path__, "stocks."):
    try:
        importlib.import_module(info.name)
    except ImportError as exc:
        print(f"{info.name}: {exc}")
"""


def test_every_module_imports_without_streamlit():
    done = subprocess.run(
        [sys.executable, "-c", SCRIPT], capture_output=True, text=True, timeout=300
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "", f"modules that need Streamlit:\n{done.stdout}"
