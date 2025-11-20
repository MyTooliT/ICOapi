all: check test

setup:
	uv venv --allow-existing
	uv sync --all-extras

check: setup
	uv run mypy .
	uv run flake8 .
	uv run pylint .

test: check
	uv run pytest

run:
	uv run python icoapi/api.py

