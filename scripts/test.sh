#!/bin/sh
# Runs the test suite inside the app container. The repo is bind-mounted at /app
# (see the `test` target in the Makefile) so the excluded-from-image tests/ dir
# is present. Dev extras aren't in the runtime image, so install them here.
set -e
pip install -q -e '.[dev]'
exec pytest -q "$@"
