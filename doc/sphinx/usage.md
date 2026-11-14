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

The API reads and changes files of both formats, whatever the variable says: The format of a file is part of the file. Endpoints that show the data of a measurement look the same for both formats. For a file with more than one source, `GET /files/analyze/{name}` and `GET /files/analyze/meta/{name}` take the query parameter `source` (the name of the source). Without it they answer `422` and list the sources, an unknown source gives `404`. A file with a single source does not need the parameter. The metadata lists all `sources` of a file with their MAC addresses, their start time and the offset (in seconds) to the earliest start of all sources, since every source has its own clock. The cloud upload sends the whole file and describes it with the metadata of its first source (pre and post metadata are the same for all sources).

### Units

With multi STU support every STU has a CAN network of its own, and every connected network is a *unit*: a network with its STU and the sensor device (STH) that is connected to it. The name of a unit is `interface:channel` of its network, e.g. `pcan:PCAN_USBBUS2`.

- `PUT /can/connect` adds the network as unit (without the variable it replaces the connected network). On startup, `ICOAPI_CAN_AUTOCONNECT=1` connects all networks that were found and skips those without an answering STU.
- `GET /can/units` lists the units. The state contains them (`units`) too. Its other fields (`can_selected`, `sth_connected`, …) describe the first unit.
- `PUT /can/disconnect?unit=…` disconnects one unit, without `unit` all of them.
- All requests that work with an STU or a sensor device (`/stu/…`, `/sth/…`) take the parameter `unit`. Without it they use the first unit.

### Measurements with all units

A measurement always uses **all** units, with the same instructions (channels, sensors, ADC). All data ends up in one file with one source per unit, named after its sensor device (a number is added to names that are used more than once).

Starting is all-or-nothing. Before anything starts, all units are checked at the same time (`GET /measurement/preflight` does the same without changing anything):

- the STU answers and a sensor device is connected,
- the connection to the sensor device is good enough (RSSI of at least `ICOAPI_MIN_RSSI`, default `-90`),
- the sensor device accepts the configuration (`/measurement/start` writes it and reads it back),
- the CAN bus of the unit can transport the data (at most `ICOAPI_MAX_MESSAGES_PER_SECOND` streaming messages per second, default `7000`).

If one unit is not ready, nothing starts and the answer (`502`) lists the problems of every unit. `POST /measurement/execute` connects the sensor devices first: give the MAC address of the sensor device of every unit in `unit_mac_addresses` (`{"simulated:SIM1": "14-2D-41-D7-77-7D", …}`). If anything fails, no unit stays connected.

While measuring, every unit streams on its own. The WebSocket sends the data of all units, every value has the name of its source in `source`. If the stream of one unit fails, the measurement fails as a whole. What was recorded until then stays in the (closed) file. A measurement can be stopped with `/measurement/stop`, which stops all units.

The clocks of the units are not synchronized. Every source has the time of its first message as `start_time` (taken from the timestamp of the message, so the start times of all units can be compared) and timestamps in microseconds since that time. `start_offset` in the `sources` of the metadata is the offset to the earliest source. The start of the units differs by the time the first message of each takes.

Not supported with several units: IFT values (`422`). A measurement with one unit works as before.

To try it without hardware, set `ICOAPI_SIMULATE_NETWORKS=2` (or more) next to `ICOAPI_SIMULATE`: every simulated network has its own STU (`02-1C-05-51-FF-0n`) and its own sensor devices (`Test-STH`, `Test-STH-2`, …).
