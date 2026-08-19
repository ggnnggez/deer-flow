install:
	uv sync

dev:
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001 --reload

gateway:
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run uvicorn app.gateway.app:app --host 0.0.0.0 --port 8001

test:
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/ -v

test-blocking-io:
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/blocking_io -q --tb=short

# Opt-in PostgreSQL tier: the migration matrix (empty -> head, head -> 0004 ->
# head, re-upgrade no-op), the three `bootstrap_schema` branches, and one
# end-to-end Ansich service smoke. Every other test runs on SQLite; this is the
# only gate that executes the migration chain against a real server.
#
#   docker run --rm -d --name deerflow-pg-test -p 5433:5432 \
#       -e POSTGRES_PASSWORD=deerflow-test postgres:16
#   export DEER_FLOW_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:deerflow-test@localhost:5433/postgres
#   make test-postgres
#   docker rm -f deerflow-pg-test
#
# Each test creates and drops its own uniquely-named database on that server, so
# the tier is re-runnable. Without the env var every test self-skips (the same
# opt-in shape as the redis tier), which is why `make test` stays SQLite-only.
test-postgres:
	@if [ -z "$$DEER_FLOW_TEST_POSTGRES_URL" ]; then \
		echo "DEER_FLOW_TEST_POSTGRES_URL is not set -- the postgres tier will self-skip."; \
		echo "Start a server and export the URL (see the comment above this target):"; \
		echo "  docker run --rm -d --name deerflow-pg-test -p 5433:5432 -e POSTGRES_PASSWORD=deerflow-test postgres:16"; \
		echo "  export DEER_FLOW_TEST_POSTGRES_URL=postgresql+asyncpg://postgres:deerflow-test@localhost:5433/postgres"; \
	fi
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run pytest tests/integration -m integration -q -rs --tb=short

lint:
	uvx ruff check .
	uvx ruff format --check .

format:
	uvx ruff check . --fix && uvx ruff format .

detect-blocking-io:
	@PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run python ../scripts/detect_blocking_io_static.py --output ../.deer-flow/blocking-io-findings.json

# Generate a new alembic revision by autogenerating the diff against the live
# ORM models. Usage: make migrate-rev MSG="add foo column to runs"
# The Gateway runs `alembic upgrade head` automatically at startup via
# `bootstrap_schema`, so there is intentionally no `migrate` / `migrate-stamp`
# target -- the single execution path keeps ops mistakes off the table.
# The script builds a fresh temp SQLite at head, then diffs the live models
# against it, so a clean checkout does NOT need a pre-existing ./data/deerflow.db.
migrate-rev:
	@if [ -z "$(MSG)" ]; then echo 'usage: make migrate-rev MSG="describe the change"'; exit 1; fi
	PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUTF8=1 uv run python scripts/_autogen_revision.py "$(MSG)"
