# Run checks and test
all: check test

# Setup Python environment
setup:
	uv venv --allow-existing
	uv sync --all-extras

# Check code with various linters
check: setup
	uv run mypy .
	uv run flake8 .
	uv run pylint .

# Run tests
test: check
	uv run pytest

# Run API server
run:
	uv run python icoapi/api.py

