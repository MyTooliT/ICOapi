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

A measurement always uses **all** units. By default every unit gets the same instructions (channels, sensors, ADC), see below for what can differ. All data ends up in one file with one source per unit, named after its sensor device (a number is added to names that are used more than once).

Starting is all-or-nothing. Before anything starts, all units are checked at the same time (`GET /measurement/preflight` does the same without changing anything):

- the STU answers and a sensor device is connected,
- the connection to the sensor device is good enough (RSSI of at least `ICOAPI_MIN_RSSI`, default `-90`),
- the sensor device accepts the configuration (`/measurement/start` writes it and reads it back),
- the CAN bus of the unit can transport the data (at most `ICOAPI_MAX_MESSAGES_PER_SECOND` streaming messages per second, default `7000`).

If one unit is not ready, nothing starts and the answer (`502`) lists the problems of every unit. `POST /measurement/execute` connects the sensor devices first: give the MAC address of the sensor device of every unit in `unit_mac_addresses` (`{"simulated:SIM1": "14-2D-41-D7-77-7D", …}`). If anything fails, no unit stays connected.

While measuring, every unit streams on its own. The WebSocket sends the data of all units, every value has the name of its source in `source`. If the stream of one unit fails, the measurement fails as a whole. What was recorded until then stays in the (closed) file. A measurement can be stopped with `/measurement/stop`, which stops all units.

**Limiting the live data.** The file always has all points, but a client that draws charts (a browser) can not handle the 3000 points per second of every unit. The WebSocket `/measurement/stream` therefore takes two optional query parameters that apply to measurements of several units: `rate` is the number of points per second **per source** that are sent (the others are left out, data loss values always arrive), and `updates` is the number of messages per second (the points collected in between are sent together, the default is the environment variable `WEBSOCKET_UPDATE_RATE`, 300). Without `rate` every point is sent, e.g. `/measurement/stream?rate=200&updates=30`. A client that can not keep up never holds the measurement up: Points wait in a buffer and the oldest ones are dropped (a warning is logged once).

The clocks of the units are not synchronized. Every source has the time of its first message as `start_time` (taken from the timestamp of the message, so the start times of all units can be compared) and timestamps in microseconds since that time. `start_offset` in the `sources` of the metadata is the offset to the earliest source. The start of the units differs by the time the first message of each takes.

**Which units measure.** While a measurement runs, `GET /measurement` (and the answer of `/measurement/start`) lists them in `units`, one entry per unit with the `unit` name, the `source` it writes to, its `tool_name` and the MAC addresses of its STU (`stu_mac_address`) and sensor device (`sth_mac_address`). The `recording/finished` and `recording/failed` events (WebSocket and MQTT) contain the same list, so a client knows the sources of the file without opening it. A measurement of one unit has a list with this unit. With multi STU support every stream frame (data, data loss, IFT) has `source`, also for one unit. A `recording/failed` event has `failed_unit` if the stream of one unit caused the error (not for errors of the file, e.g. a full disk). `GET /files` lists the names of the `sources` of a file (`null` for files in the old format). Without multi STU support `units` is `null` in the status and missing in the events. The state (`/state`, state messages on the WebSocket and the MQTT state topic) lists the connected units in `units` with their connection state, and it is published again whenever a unit connects, disconnects or its sensor device changes.

### Instructions for single units

The tool holders of different units often have different sensors. The instructions of a measurement are the ones of every unit, `units` changes them for single units (the name of the unit -> instructions):

```json
{
  "name": "Two holders",
  "time": 10,
  "first": {"sensor_id": "acc100g"},
  "second": {"sensor_id": null},
  "third": {"sensor_id": null},
  "adc": {"prescaler": 2, "acquisition_time": 8, "oversampling_rate": 64, "reference_voltage": 3.3},
  "units": {
    "pcan:PCAN_USBBUS2": {
      "second": {"sensor_id": "acc50g"},
      "adc": {"prescaler": 2, "acquisition_time": 8, "oversampling_rate": 32, "reference_voltage": 3.3},
      "mac_address": "14-2D-41-D7-77-7D"
    }
  }
}
```

A unit can have its own `first`, `second`, `third`, `adc`, `sensor_configuration` and `mac_address` (the sensor device `/measurement/execute` connects). What is set replaces the value of the measurement for this unit, everything else is kept. A channel is replaced as a whole: To disable one that the measurement enables, set its `sensor_id` to `null`. Name, time, metadata, `wait_for_post_meta` and `disconnect_after_measurement` are the same for all units.

Every unit is checked for what it does: the load of its CAN bus follows from its own channels and ADC settings, so only the unit with too many messages is not ready. Instructions for a unit that does not exist, or a sensor that does not exist for a unit, are an error (`422`, naming the unit). Without multi STU support `units` is refused (`422`), since ignoring it would measure something else than was asked for. With one unit, the instructions for that unit are applied.

### Writing the measurement file

A thread of its own writes the measurement file, so a disk that is slow for a moment does not hold up the streams. The data waits in a queue (about 2 minutes of the data of a unit). If the disk is so slow that the queue is full, or if writing fails (e.g. the disk is full), the measurement fails with an error that says so, instead of losing data without notice. The file is closed correctly and keeps what was written. The file is flushed to disk every few seconds.

Not supported with several units: IFT values (`422`). A measurement with one unit works as before.

To try it without hardware, set `ICOAPI_SIMULATE_NETWORKS=2` (or more) next to `ICOAPI_SIMULATE`: every simulated network has its own STU (`02-1C-05-51-FF-0n`) and its own sensor devices (`Test-STH`, `Test-STH-2`, …).
