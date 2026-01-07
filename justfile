# -- Settings ------------------------------------------------------------------

# Use latest version of PowerShell on Windows
set windows-shell := ["pwsh.exe", "-NoLogo", "-Command"]

# -- Variables -----------------------------------------------------------------

package := "icoapi"
location := "localhost:33215/api/v1"
http_url := "http://" + location
ws_url := "ws://" + location
mac_address := "08-6B-D7-01-DE-81"
name := "Test-STH"
measurement_name := "Test Measurement"

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
test *options: check
	uv run pytest {{options}} --reruns 5 --reruns-delay 1

# Run hardware-independent tests
[group('test')]
test-no-hardware: (test "-m 'not hardware'")

# Run API server
[group('run')]
run:
	uv run python "{{package}}/api.py"

# Release new package version
[group('release')]
[unix]
release version:
	#!/usr/bin/env sh -e
	uv version {{version}}
	version="$(uv version --short)"
	git commit -a -m "Release: Release version ${version}"
	git tag "${version}"
	git push
	git push --tags

# Release new package version
[group('release')]
[windows]
release version:
	#!pwsh
	uv version {{version}}
	set version "$(uv version --short)"
	git commit -a -m "Release: Release version ${version}"
	git tag "${version}"
	git push
	git push --tags

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
[group('http')]
disconnect:
	http PUT "{{http_url}}/sth/disconnect"

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
	  first[channel_number]:=1 \
	  first[sensor_id]=acc100g_01 \
	  second[channel_number]:=0 \
	  second[sensor_id]="" \
	  third[channel_number]:=0 \
	  third[sensor_id]="" \
	  ift_requested:=false \
	  ift_channel="" \
	  ift_window_width:=0 \
	  adc[prescaler]:=2 \
	  adc[acquisition_time]:=8 \
	  adc[oversampling_rate]:=64 \
	  adc[reference_voltage]:=3.3 \
	  meta[version]="" \
	  meta[profile]="" \
	  meta[parameters]:={}

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
