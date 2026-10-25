# Quality gate. `make check` must pass before anything is called done.
.PHONY: check lint types test test-fast migrate-check openapi audit

check: lint types migrate-check test

lint:
	uv run ruff check .
	uv run ruff format --check .

types:
	uv run mypy

test:
	uv run pytest -q --cov

test-fast:
	uv run pytest tests/unit -q

migrate-check:
	uv run alembic check

openapi:
	uv run python scripts/export_openapi.py

# Known-vulnerability scan of the locked dependencies (needs network).
audit:
	uv export --frozen --no-hashes --format requirements-txt > /tmp/nb-req.txt
	uvx pip-audit -r /tmp/nb-req.txt
