#!/usr/bin/env bash
# Run the API test suite.
#
# PYTHONPATH is cleared and plugin autoload disabled because a system-wide
# PYTHONPATH (ROS, for instance) otherwise leaks third-party pytest plugins
# into the venv and breaks collection before any test runs.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT/api"
[ -d .venv ] || uv venv --python 3.12 .venv
uv pip install -q -e . pytest --python .venv/bin/python
PYTHONPATH= PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 exec .venv/bin/python -m pytest "$@"
