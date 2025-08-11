# -- Variables -----------------------------------------------------------------

MODULE = icoapi
TEST_DIRECTORY = test
URL = http://localhost:33215/api/v1
MAC_ADDRESS = 08-6B-D7-01-DE-81
NAME = "Test-STH"

# -- Rules ---------------------------------------------------------------------

all: check test

.PHONY: check
check:
	poetry run mypy .
	poetry run flake8 $(TEST_DIRECTORY)

.PHONY: test
test:
	poetry run pytest

.PHONY: run
run: check
	poetry run python3 $(MODULE)/api.py
	
.PHONY: reset
reset:
	http PUT "$(URL)/stu/reset"

.PHONY: connect
connect:
	http PUT "$(URL)/sth/connect" mac=$(MAC_ADDRESS)
	
.PHONY: disconnect
disconnect:
	http PUT "$(URL)/sth/disconnect"
	
.PHONY: start-measurement
start-measurement:
	http POST "$(URL)/measurement/start" \
	  name="$(NAME)" \
	  mac="$(MAC_ADDRESS)" \
	  time=10 \
	  first[channel_number]:=1 \
	  first[sensor_id]="acc100g_01" \
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
	  meta[parameters]:=\{\}
	  
.PHONY: measurement-status
status:
	http GET "$(URL)/measurement"
	  
.PHONY: stop-measurement
stop-measurement:
	http POST '$(URL)/measurement/stop'              
