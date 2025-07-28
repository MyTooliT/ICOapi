# ICOapi

A REST and WebSocket API using the Python FastAPI library. You can find the official documentation [here](https://fastapi.tiangolo.com/).

We currently support

- Windows 10+,
- Debian/Linux, and
- macOS.

Additionally, when the API is running, it hosts an OpenAPI compliant documentation under `/docs`, e.g. under [`localhost:33215/docs`](http://localhost:33215/docs).
# Installation

This repository can be setup manually for Windows and Linux or using the installation script for Linux.

## Prerequisites

- Python 3.10+, from the official [Python Website](https://www.python.org/downloads/)
- [Poetry](https://python-poetry.org) (for development)

## Manual Installation (Development)

```
poetry lock && poetry install
```

## Service Installation (Linux)

For Linux, there is an installation script which sets the directory for the actual installation, the directory for the
systemd service and the used systemd service name. The (sensible) defaults are:

```
SERVICE_NAME="icoapi"
INSTALL_DIR="/etc/icoapi"
SERVICE_PATH="/etc/systemd/system"
```

Please note that the install script expects that the root folder of the repository contains an `.env` configuration file. You can use `example.env` as starting point:

```sh
cp example.env .env
```

After you created the configuration file, run the script to install normally:

```sh
./install.sh
```

Or, if you want to delete existing installations and do a clean reinstall, add the `--force` flag:

```sh
./install.sh --force
```

# Configuration / Environment Variables

This application has two main forms of configuration: environment variables and auto-generated metadata types/classes.

## Environment Variables

The application expects a `.env` file in the root directory, meaning on the same level as the main entrypoint file. It
handles the main configuration of the backend application.

> All variables prefixed with `VITE_` indicate that there is a counterpart in the client side environment variables. This
is to show that changes here most likely need to be propagated to the client (and electron wrapper, for that matter).

### Client/API Connection Settings

These settings determine all forms of client/API communication details.

The main REST API is versioned, does _NOT_ use SSL at the moment and has certain origins set as secure for CORS.

```
VITE_API_PROTOCOL=http
VITE_API_HOSTNAME="0.0.0.0"
VITE_API_PORT=33215
VITE_API_VERSION=v1
VITE_API_ORIGINS="http://localhost,http://localhost:5173,http://localhost:33215,http://127.0.0.1:5173"
```

The WebSocket is for streaming data. It only requires a `VITE_API_WS_PROTOCOL` variable akin to `VITE_API_PROTOCOL`
which decided between SSL or not, and how many times per second the WebSocket should send data.

```
VITE_API_WS_PROTOCOL=ws
WEBSOCKET_UPDATE_RATE=60
```

### File Storage Settings

These settings determine where the measurement files are stored locally. There are two options, which you should
**not use together** to remove ambiguity:

```
VITE_BACKEND_MEASUREMENT_DIR=icodaq
# OR
VITE_BACKEND_FULL_MEASUREMENT_PATH=C:\Users\breurather\AppData\Local\icodaq
```

`VITE_BACKEND_MEASUREMENT_DIR` expects a single folder name and locates that folder under a certain path
- On Windows, that path is `%LocalAppData%`
- On Linux, it is the first available of:
  - `$XDG_DATA_DIRS`
  - `"/usr/local/share:/usr/share"`
- On macOS it is the directory `Library/Application Support` in the user’s home folder

`VITE_BACKEND_FULL_MEASUREMENT_PATH` lets you override the default pathing and tries to create the folder at your
supplied location.
- Use this at your own discretion as not having a writable directory for measurements will crash the program.
- This is unfortunately not OS-agnostic for now.

### Trident Data Storage Settings

These settings control the implementation of the Trident API to use as a connected data storage. It requires credentials
and needs to be explicitly enabled by setting the `TRIDENT_API_ENABLED` to `True`

The complete service will be composed as ``<TRIDENT_API_PROCOTOL>://<TRIDENT_API_DOMAIN>/<TRIDENT_API_BASE_PATH>``. This 
separation of the URI parts enables automatic setting of domain-specific cookies for token storage.

Please note that the base path is set _without_ the leading ``/`` for simplicity. If more complex paths are the default
base, they need to be entered as ``trident/v1/api`` for example.

```
TRIDENT_API_ENABLED=True
TRIDENT_API_USERNAME=...
TRIDENT_API_PASSWORD=...
TRIDENT_API_BUCKET="ctd-data-storage"
TRIDENT_API_BUCKET_FOLDER="default"
TRIDENT_API_PROTOCOL=https
TRIDENT_API_DOMAIN=iot.ift.tuwien.ac.at
TRIDENT_API_BASE_PATH=trident
```

### Logging Settings

```
LOG_LEVEL=DEBUG
LOG_USE_JSON=0
LOG_USE_COLOR=1
LOG_PATH="C:\Users\breurather\AppData\Local\icodaq\logs"
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
LOG_NAME_WITHOUT_EXTENSION=icodaq
```

``LOG_LEVEL`` is one of `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`

``LOG_USE_JSON`` formats the logs in plain JSON if set to `1`
- useful for production logs

``LOG_USE_COLOR`` formats the logs in color if set to `1`
- useful for local development in a terminal

``LOG_PATH`` overrides the default log location as an absolute path to a directory
- You **need** to have permissions
- The defaults are:
  - Windows: ``AppData/Local/icodaq/logs``
  - Linux/macOS: ``~/.local/share/icodaq/logs``

``LOG_NAME_WITHOUT_EXTENSION`` sets the name of the logfile. Without any file extension.

``LOG_MAX_BYETS`` and `LOG_BACKUP_COUNT` determine the maximum size and backup number of the logs.

## Metadata Type/Class Generation

To support the usage of arbitrary metadata when creating measurements, a configuration system has been set up. This
system starts as an Excel file in which all metadata fields are defined. This file is then parsed into a YAML file, from
which it can be used further.

The complete metadata logic can be found in the ICOweb repository.

The metadata is split into two parts:
- the metadata to be entered __before__ a measurement starts (pre_meta)
- the metadata to be entered __after__ the measurement has been ended (post_meta)

This ensures that common metadata like machine tool, process or cutting parameters are set beforehand while keeping the
option to require data after the fact, such as pictures or tool breakage reports.

The pre-meta is sent with the measurement instructions while the post-meta is communicated via the open measurement WebSocket.

## Measurement Value Conversion / Storage

The used `ICOc` library streams the data as unsigned 16-bit integer values. To get the actual measured physical values,
we go through two conversion steps:

### Step 1: 16-bit ADC value to Voltage

The streamed ``uint16`` is a direct linear map from `0 - 2^16` to `0 - V_ref` of the used ADC. This means we can reverse the conversion
by inverting the linear map.

> We will define the coefficients ``k1`` and `d1` as the factor and offset of going from bit-value to voltage respectively.

As the linear map is direct and without an offset, we can set:

```
d1 = 0
k1 = (V_ref)/(2^16) in Volt
```

> **The first conversion only depends on the used reference voltage.**

### Step 2: Voltage to Physical Value

Each used sensor has a datasheet and associated linear coefficients to get from voltage output to the measured physical values.

> We will define ``k2`` and ``d2`` as the linear coefficients of going from voltage to physical measurement.

The API now accepts a ``sensor_id`` which can be used to choose a unique sensor for the conversion and has the current
IFT channel-sensor-layout as defaults.

# Run

On Linux, if the installation script was used, the service runs automatically - but as-is, without any updates on
changes to the repository as the service simply installs the current version.

For any other usage or for local development, run:

```shell
poetry run python3 api.py
```

# Development Guidelines

These guidelines are a work-in-progress and aim to explain development decisions and support consistency.

## Logging

The application is set up to log _everything_. This is how the logging is set up.

### Guidelines

- Log only after success
- Don't log intent, like "Creating user..." or "Initializing widget..." unless it's for debugging.
- Do log outcomes, like "User created successfully." — but only after the operation completes without error.
- Avoid logging in constructors unless they cannot fail
  - Prefer logging in methods that complete the actual operation,
  - or use a factory method to wrap creation and success logging.

### Levels

| Action                            | Log Level            | Description (taken from [Python docs](https://docs.python.org/3/library/logging.html#logging-levels)) |
|-----------------------------------|----------------------|-------------------------------------------------------------------------------------------------------|
| Starting a process / intention    | `DEBUG`              | Detailed information for diagnosing problems. Mostly useful for developers.                           |
| Successfully completed action     | `INFO`               | For confirming that things are working as expected.                                                   |
| Recoverable error / edge case     | `WARNING`            | Indicates something unexpected happened or could cause problems later.                                |
| Expected failure / validation     | `ERROR`              | Used for serious problems that caused a function to fail.                                             |
| Critical Failure / unrecoverable  | `CRITICAL`           | For very serious errors. Indicates a critical condition — program may abort.                          |
| Unexpected exception (with trace) | `logger.exception()` | Serious errors, but the exception was caught.                                                         |

# Example Requests

**Note:** The sample requests below use the [command line version of httpie](https://httpie.io/cli)

Get list of available sensor devices:

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

Connect to available sensor device:

```sh
http PUT 'http://localhost:33215/api/v1/sth/connect' mac='08-6B-D7-01-DE-81'
```

Check if the STU is connected to the sensor device:

```sh
http POST 'http://localhost:33215/api/v1/stu/connected' name='STU 1'
```

Disconnect from sensor device:

```sh
http PUT http://localhost:33215/api/v1/sth/disconnect
```
