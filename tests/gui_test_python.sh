#!/bin/sh
# Explicit test interpreter shim. Never used by the normal game launcher.
AVALON_TEST_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
AVALON_TEST_PYTHON="$AVALON_TEST_ROOT/.venv/bin/python"
if [ ! -x "$AVALON_TEST_PYTHON" ]; then
    AVALON_TEST_PYTHON=python3
fi
exec "$AVALON_TEST_PYTHON" "$AVALON_TEST_ROOT/tests/gui_test_backend.py" "$@"
