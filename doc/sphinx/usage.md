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

## Multi STU Support (Experimental)

Set the environment variable `MUTLI_STU_SUPPORT=1` (`MULTI_STU_SUPPORT=1` works too) to store measurements as [ICOschema](https://github.com/ift-tuwien/ICOschema) bundles, instead of in the format of the `Storage` class of ICOtronic. A bundle is a HDF5 file with one *source* (one STU/STH combination) per data stream. Without the variable the API behaves as before.

What is different in a bundle:

- The values are stored in the unit of the sensor, as they always were. The `conversion` of the channel (a linear conversion from the voltage to the unit of the sensor) says what was applied to the raw values. It must not be applied again.
- The timestamps are microseconds since the start time of the source, the data type of the other columns is the same as before.
- Pictures are stored in the group `pictures`, embedded files in the group `files`.
- Everything that ICOschema has no field for (which streaming slot a channel is, the sensors as configured, the name of the tool, …) is stored in the `additional_data` of the source, below the key `icoapi`.

The API reads and changes files of both formats, whatever the variable says: The format of a file is part of the file. Endpoints that show the data of a measurement look the same for both formats. Files with more than one source are not supported by them yet (`501`).

Only one STU is supported at the moment: this switches the file format, not (yet) the number of STUs the API can use.
