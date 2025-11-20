all: check test

check:
	uv run mypy .
	uv run flake8 .
	uv run pylint .

test:
	uv run pytest

run:
	uv run python icoapi/api.py

