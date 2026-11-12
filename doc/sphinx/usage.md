# Usage

The example commands below use the [command line version of httpie](https://httpie.io/cli). For more information on the specific endpoints, please take a look at the documentation which should be available under the endpoint `/docs`, e.g. [`localhost:33215/docs`](http://localhost:33215/docs), after [you installed and setup](install:installation-and-setup) ICOapi. A static version of the API documentation is also available in the [section “API”](#openapi-documentation).

## Get List of Available Sensor Devices

```sh
http 'http://localhost:33215/api/v1/sth'
```

Example output:

```json
[
  {
    "device_number": 0,
    "mac_address": "08-6B-D7-01-DE-81",
    "name": "Test-STH",
    "rssi": -44
  }
]
```

## Connect to Available Sensor Device

```sh
http PUT 'http://localhost:33215/api/v1/sth/connect' mac_address='08-6B-D7-01-DE-81'
```

## Check if the STU is Connected to the Sensor Device

```sh
http POST 'http://localhost:33215/api/v1/stu/connected' name='STU 1'
```

## Disconnect from Sensor Device

```sh
http PUT 'http://localhost:33215/api/v1/sth/disconnect'
```

## Search and Connect to a CAN Network

```sh
http GET 'http://localhost:33215/api/v1/can/networks'
http PUT 'http://localhost:33215/api/v1/can/connect' interface=pcan channel=PCAN_USBBUS1
http PUT 'http://localhost:33215/api/v1/can/disconnect'
```

If you do not specify a network, `PUT /can/connect` uses the default network for your platform (or else the first network found). To connect on startup, set the environment variable `ICOAPI_CAN_AUTOCONNECT=1`.

## Run Without Hardware (Simulation)

To try or test the whole software without CAN adapter, STU and sensor devices, set the environment variable `ICOAPI_SIMULATE`:

- `ICOAPI_SIMULATE=1` adds the CAN network `simulated:SIM1` to the networks that are found. Connect to it like to any other network (`PUT /can/connect` or the CAN panel of the client).
- `ICOAPI_SIMULATE=only` offers only the simulated network. This is what the tests use.

```sh
ICOAPI_SIMULATE=1 ICOAPI_CAN_AUTOCONNECT=1 uv run icoapi
```

The simulation replaces the STU and the sensor devices, everything else (state handling, API, measurement files, events) is the real code:

| | Simulation |
| --- | --- |
| STU | MAC address `02-1C-05-51-FF-01`, resets take a moment |
| Sensor devices | `Test-STH` (`14-2D-41-D7-77-7D`, the MAC of the development board) and `Sim-STH2` (`02-1C-05-51-00-02`). Renaming, ADC and sensor configuration work and are kept until the API stops. Set `ICOAPI_SIMULATE_DEVICES=Name=MAC,Name=MAC` to simulate other devices. |
| Measurements | Sine waves (50, 120 and 310 Hz for the first, second and third slot) plus noise around the middle of the ADC range, in real time. Message rate and values per message follow the ADC and channel configuration. |

Two more variables change the behavior: `ICOAPI_SIMULATE_LATENCY` (seconds for scanning, connecting and resetting, default `0.2`) and `ICOAPI_SIMULATE_DATALOSS` (probability that a streaming message is lost, default `0`).

Measurement files created with the simulation contain the attribute `simulated` (`true`), since their data must never be mistaken for a real measurement. Run the tests that usually need hardware against the simulation with `just test-simulated`. It uses its own data folder (`ICOdaq-simulated`), so your own measurements are not touched.
