# -- Settings ------------------------------------------------------------------

# Use latest version of PowerShell on Windows
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# -- Variables -----------------------------------------------------------------

package := "icoapi"
location := "localhost:33215/api/v1"
http_url := "http://" + location
mac_address := "08-6B-D7-01-DE-81"

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
	uv run python "{{package}}/api.py"

# ========
# = HTTP =
# ========

# Reset STU
[group('http')]
reset:
	http PUT "{{http_url}}/stu/reset"

# Connect to sensor node
[group('http')]
connect:
	http PUT "{{http_url}}/sth/connect" "mac_address={{mac_address}}"

# Disconnect from sensor node
disconnect:
	http PUT "{{http_url}}/sth/disconnect"
