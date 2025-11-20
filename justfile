# -- Settings ------------------------------------------------------------------

# Use latest version of PowerShell on Windows
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# -- Variables -----------------------------------------------------------------

package := "icoapi"

# -- Recipes -------------------------------------------------------------------

# Setup Python environment
[group('setup')]
setup:
	uv venv --allow-existing
	uv sync --all-extras

# Check code with various linters
[group('lint')]
check: setup
	uv run mypy .
	uv run flake8 .
	uv run pylint .

# Run tests
[group('test')]
[default]
test: check
	uv run pytest

# Run API server
[group('run')]
run:
	uv run python {{package}}/api.py

