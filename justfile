# -- Settings ------------------------------------------------------------------

# Use latest version of PowerShell on Windows
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]
# Load `.env` file data for environment variables
set dotenv-load := true

# -- Variables -----------------------------------------------------------------

package := "icoapi"

location := "localhost:33215/api/v1"
http_url := "http://" + location
ws_url := "ws://" + location
mac_address := env("TEST_SENSOR_NODE_EUI", "08-6B-D7-01-DE-81")
name := "Test-STH"
measurement_name := "Test Measurement"

sphinx_directory := "sphinx"
sphinx_input_directory := "doc/sphinx"

# -- Recipes -------------------------------------------------------------------

# Setup Python environment
[group('setup')]
setup:
	uv venv --allow-existing
	uv sync --all-extras

# Reset CAN adapter (release it, flush buffers, search for networks again)
[group('setup')]
reset-can:
	uv run python -c "import asyncio; from icoapi.models.globals import ICOsystemSingleton; asyncio.run(ICOsystemSingleton.reset())"

# Check code: formatting, linting and types; optionally only the given files
[group('lint')]
check *files: setup
	uv run ruff format --check {{ if files == "" { "." } else { files } }}
	uv run ruff check {{ if files == "" { "." } else { files } }}
	uv run mypy {{ if files == "" { "." } else { files } }}

# Format code and apply safe lint fixes
[group('lint')]
fix: setup
	uv run ruff format
	uv run ruff check --fix

# Run hardware-independent tests (this is what CI and `release` run)
[default]
[group('test')]
test *options: check
	uv run pytest -m "not hardware" {{options}} --reruns 5 --reruns-delay 1

# Run only the hardware tests (never run in CI)
[group('test')]
test-hardware *options: check
	uv run pytest -m hardware {{options}} --reruns 5 --reruns-delay 1

# Run all tests, including the ones that need hardware, with simulated hardware (uses its own data folder `ICOdaq-simulated`, not your measurements)
[group('test')]
[unix]
test-simulated *options: check
	ICOAPI_SIMULATE=only ICOAPI_SIMULATE_LATENCY=0.05 VITE_APPLICATION_FOLDER=ICOdaq-simulated uv run pytest {{options}}

# Run all tests, including the ones that need hardware, with simulated hardware (uses its own data folder `ICOdaq-simulated`, not your measurements)
[group('test')]
[windows]
test-simulated *options: check
	$env:ICOAPI_SIMULATE = 'only'; $env:ICOAPI_SIMULATE_LATENCY = '0.05'; $env:VITE_APPLICATION_FOLDER = 'ICOdaq-simulated'; uv run pytest {{options}}

# Run tests that need an MQTT broker (set `TEST_MQTT_BROKER` and, if required, `TEST_MQTT_PORT`, `TEST_MQTT_USERNAME`, `TEST_MQTT_PASSWORD`)
[group('test')]
test-mqtt: check
	uv run pytest -m mqtt

# Run API server
[group('run')]
run:
	uv run python "{{package}}/api.py"

# Release new version: `just release 1.2.3` (see scripts/release.py)
[group('release')]
release version:
	uv run scripts/release.py {{version}}

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

# List sensor nodes
[group('http')]
list:
	http GET "{{http_url}}/sth"

# Disconnect from sensor node
[group('http')]
disconnect:
	http PUT "{{http_url}}/sth/disconnect"

# Rename sensor node
[group('http')]
rename:
	http PUT "{{http_url}}/sth/rename" "mac_address={{mac_address}}" \
		"new_name={{name}}"

# Get sensor configuration
[group('http')]
sensor:
	http GET "{{http_url}}/sensor"

# Start measurement
[group('http')]
start-measurement: connect
	http POST "{{http_url}}/measurement/start" \
	  "name={{measurement_name}}" \
	  "mac_address={{mac_address}}" \
	  time=100 \
	  first[sensor_id]=acc100g_01 \
	  second[sensor_id]:=null \
	  third[sensor_id]:=null \
	  ift_requested:=true \
	  ift_channel="first" \
	  ift_window_width:=50 \
	  adc[prescaler]:=2 \
	  adc[acquisition_time]:=8 \
	  adc[oversampling_rate]:=64 \
	  adc[reference_voltage]:=3.3 \
	  meta[version]="" \
	  meta[profile]="" \
	  meta[parameters]:={}

# Add post-meta measurement data to a measurement file, e.g. `just set-post-measurement-data <name>.hdf5`
[group('http')]
set-post-measurement-data measurement_file:
	http POST "{{http_url}}/files/post_meta/{{measurement_file}}" \
	  version="1.0" \
	  profile="default" \
	  parameters[test_post_metadata]="something"

# Check measurement status
[group('http')]
status:
	http GET "{{http_url}}/measurement"

# Connect to measurement socket
[group('http')]
stream:
	http "{{ws_url}}/measurement/stream"

# Stop current measurement
[group('http')]
stop-measurement:
	http POST "{{http_url}}/measurement/stop"

# =================
# = Documentation =
# =================

# Generate documentation
[group('documentation')]
documentation: setup
	uv run sphinx-build -M html {{sphinx_input_directory}} {{sphinx_directory}}

# Remove documentation
[group('documentation')]
[windows]
clean:
	#!pwsh
	Remove-Item -Recurse {{sphinx_directory}}

# Remove documentation
[group('documentation')]
[unix]
clean:
	#!/usr/bin/env sh -e
	rm -rf {{sphinx_directory}}
