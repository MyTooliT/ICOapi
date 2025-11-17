# ICOapi

A REST and WebSocket API using the Python FastAPI library. You can find the official documentation [here](https://fastapi.tiangolo.com/).

We currently support all operating systems which can run Python 3.10. and use a CAN interface properly

When the API is running, it hosts an OpenAPI compliant documentation under `/docs`, e.g. under [`localhost:33215/docs`](http://localhost:33215/docs).

# Hardware

This API is designed to interact with the ICOtronic system and thus only reasonably works with this system connected.

To get a complete experience, even for development, you need:
- A CAN interface (usually either PCAN-USB or the RevPi CAN Module)
- The proper drivers

## Linux

On Linux, the API (rather: the underlying CAN library) requires:
- The proper driver for your CAN device (PCAN-USB if used)
- The CAN port set up as described in [this guide](https://mytoolit.github.io/ICOc/#introduction:section:pcan-driver:linux)
  - Including the setup for ``systemd-networkd``!


# Installation for Development

This repository can be setup manually, installed as a system service on Linux-based systems or deployed using Docker on 
Linux-based systems.

If none of the versions for deploying properly (see chapter [Run](#run)) work for you, you can always "deploy" by 
cloning this repository and running the Python script manually.

## Prerequisites

- Python 3.10+, from the official [Python Website](https://www.python.org/downloads/)
- [Poetry](https://python-poetry.org)
- Support for Python virtual environments (recommended)

Clone the repository and navigate into it to set up your virtual environment:

``git clone ... && cd ...``

``python -m venv .venv``

``source ./.venv/bin/activate`` on Linux or ``.\.venv\Scripts\activate`` on Windows

Then run the following command to get up and running:

```shell
poetry lock && poetry install --all-extras
```

Once you have that, get a baseline `.env` and run the API:

```shell
cp example.env .env
```

```shell
poetry run python3 icoapi/api.py
```

# Run

Proper deployment (automatic restart, etc.) can be done using the system service installation or Docker.

## System Service Installation (Linux)

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

## Docker (Linux)

You can use our [`Dockerfile`](Dockerfile) to build a [Docker](https://www.docker.com) image for the API:

```sh
docker build -t icoapi .
```

To run a container based on the image you can use the following command:

```sh
docker run --network=host icoapi
```

**Note:** The option `--network=host` is required to give the container access to the CAN adapter. As far as we know using the CAN adapter this way only works on a **Linux host**. For other **more secure options** to map the CAN adapter into the container, please take a look at:

- the [documentation of the ICOtronic library](https://mytoolit.github.io/ICOtronic/#docker-on-linux), and
- the article [“SocketCAN mit Docker unter Linux”](https://chemnitzer.linux-tage.de/2021/de/programm/beitrag/210/).




# Environment Variables

The application expects a `.env` file in one of three locations, each one being
the fallback for the location before. The respective function is written as:

```python
def load_env_file():
    # First try: local development
    env_loaded = load_dotenv(os.path.join(os.getcwd(), "config", ".env"), verbose=True)
    if not env_loaded:
        # Second try: configs directory
        logger.warning(f"Environment variables not found in local directory. Trying to load from app data: {get_config_dir()}")
        env_loaded = load_dotenv(os.path.join(get_config_dir(), ".env"), verbose=True)
    if not env_loaded and is_bundled():
        # Third try: we should be in the bundled state
        bundle_dir = sys._MEIPASS
        logger.warning(f"Environment variables not found in local directory. Trying to load from app data: {bundle_dir}")
        env_loaded = load_dotenv(os.path.join(bundle_dir, "config", ".env"), verbose=True)
    if not env_loaded:
        logger.critical(f"Environment variables not found")
        raise EnvironmentError(".env not found")
```

1) For local development: the `.env` file is under `/config/.env`
2) For normal usage, the file is in the `user_data_dir`
3) When no environment variable file was found, we check the bundle directory
from the pyinstaller for the bundled file

This means that the `.env` file is bundled at compile-time and if the user has
not ever run the software or deleted the `user_data_dir` we can take it as a 
fallback.


> All variables prefixed with `VITE_` indicate that there is a counterpart in the client side environment variables. This
is to show that changes here most likely need to be propagated to the client (and electron wrapper, for that matter).

## Client/API Connection Settings

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

## File Storage Settings

These settings determine where the measurement and configuration files are stored locally.

```
VITE_APPLICATION_FOLDER=ICOdaq
```

`VITE_APPLICATION_FOLDER` expects a single folder name and locates that folder under a certain path. 
We use the `user_data_dir()` from the package `platformdirs` to simplify this. The system always logs which folder is used for storage.

## Logging Settings

```
LOG_LEVEL=DEBUG
LOG_USE_JSON=0
LOG_USE_COLOR=1
LOG_PATH="C:\Users\breurather\AppData\Local\icodaq\logs"
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
LOG_NAME_WITHOUT_EXTENSION=icodaq
LOG_LEVEL_UVICORN=INFO
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

``LOG_LEVEL_UVICORN`` controls the log level for the uvicorn webserver logging.

# Configuration Files

The API currently works with 3 configuration files in the `.yaml` format.

When the API is run, it checks for the availability of these files in the 
`<user_data_dir> / config`. If the files are not there, the defaults from the
compile time are used.

You can find the default files for all three types under `/config`.

## Configuration File Header

In each configuration file there must be a header containing information on the
file and schema.

```yaml
info:
  schema_name: sensors_schema
  schema_version: 0.0.1
  config_name: General Purpose Sensor File
  config_date: '2025-10-07T13:52:40+0200'
  config_version: 0.0.1
```

The above section is exemplary for a sensor configuration file.

## Configuration File 1: Sensors

The internal library starts the measurement based on selected channels. It is 
up to the user to know which channels are connected to which sensors currently.

To help this selection and make using the system easier, a layer of abstraction
is present in this API and thus in the client and ICOdaq software packages.

### Data Structure

Withing the ``sensors.yaml`` file, two separate areas exist. One contains the
sensor information and one the configurations which reference the sensors.
Additionally, a field for the default configuration exists. The file then looks
like this:

```yaml
info:
  ...
sensors:
- ...
- ...

sensor_configurations:
- ...
- ...

default_configuration_id: 
```

#### Sensor Data Structure

The sensors (which are written to the ``*.hdf5`` file when used) are defined as:

```yaml
- name: Acceleration 100g
  offset: -125.0
  phys_max: 100.0
  phys_min: -100.0
  scaling_factor: 75.75757575757575
  sensor_id: acc100g_01
  sensor_type: ADXL1001
  unit: g
  dimension: Acceleration
  volt_max: 2.97
  volt_min: 0.33
```

This example defines the mainly used +-100g acceleration sensor in the X axis.

Note that the field ``sensor_id`` is what the API uses to identify the sensor for usage.

#### Sensor Configuration Data Structure

This is what actually affects the client. Configurations are what the user can choose from and what determines which
sensors and channels a user can select for measurement.

The data is structured as follows:

```yaml
- configuration_id: singleboard_GYRO
  configuration_name: GYRO
  channels:
    1:  { sensor_id: acc100g_01 }
    6:  { sensor_id: photo_01 }
    8:  { sensor_id: gyro_01 }
    10: { sensor_id: vbat_01 }
```

The ``configuration_id`` is what the client-side `.env` file can set to load as a default for tools.

The ``configuration_name`` is displayed as the client.

The mapping of sensors follows the schema of ``<channel>: { sensor_id: <sensor_id> }``.

The ``default_configuration_id`` has one of the `configuration_id` set.

## Config File 2: Metadata

To support the usage of arbitrary metadata when creating measurements, a 
configuration system has been set up. This system starts as an Excel file in 
which all metadata fields are defined. This file is then parsed into a YAML 
file, from which it can be used further.

The complete metadata logic can be found in the ICOweb repository.

The metadata is split into two parts:
- the metadata entered __before__ a measurement starts (pre_meta)
- the metadata entered __after__ the measurement has been ended (post_meta)

This ensures that common metadata like machine tool, process or cutting 
parameters are set beforehand while keeping the option to require data after 
the fact, such as pictures or tool breakage reports.

The pre-meta is sent with the measurement instructions while the post-meta is 
communicated via the open measurement WebSocket.

## Configuration File 3: Dataspace

This file sets the dataspace connection settings if required. It simply holds
all the relevant information as:

````yaml
connection:
  enabled: False
  username: myUser
  password: strongPw123!
  bucket: common
  bucket_folder: default
  protocol: https
  domain: trident.example.com
  base_path: api/v1
````

All relevant fields are strings without any `/` before or after the value. This
means that for the given example a complete endpoint would be:

`https://trident.example.com/api/v1/<endpoint>`

And the relevant storage would be in the folder `default` of the bucket 
`common`.

# Measurement Value Conversion / Storage

The used `ICOc` library streams the data as unsigned 16-bit integer values. To get the actual measured physical values,
we go through two conversion steps:

## Step 1: 16-bit ADC value to Voltage

The streamed ``uint16`` is a direct linear map from `0 - 2^16` to `0 - V_ref` of the used ADC. This means we can reverse the conversion
by inverting the linear map.

> We will define the coefficients ``k1`` and `d1` as the factor and offset of going from bit-value to voltage respectively.

As the linear map is direct and without an offset, we can set:

```
d1 = 0
k1 = (V_ref)/(2^16) in Volt
```

> **The first conversion only depends on the used reference voltage.**

## Step 2: Voltage to Physical Value

Each used sensor has a datasheet and associated linear coefficients to get from voltage output to the measured physical values.

> We will define ``k2`` and ``d2`` as the linear coefficients of going from voltage to physical measurement.

The API now accepts a ``sensor_id`` which can be used to choose a unique sensor for the conversion and has the current
IFT channel-sensor-layout as defaults.

# Test

**Note:** Running the tests (successfully) requires that 

- you connected a STU to your test system and
- at least one sensor device (e.g. STH) is available.

```sh
poetry run pytest
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

## Release

**Note:** In the text below we assume that you want to release version `<VERSION>` of the package. Please just replace this version number with the version that you want to release (e.g. `0.2.0`).

1. Make sure that all the checks and tests work correctly locally

   ```sh
   make
   ```

2. Make sure all [workflows of the CI system work correctly](https://github.com/MyTooliT/ICOapi/actions)

4. Release a new version on [PyPI](https://pypi.org/project/icoapi/):
   1. Increase version number
   2. Add git tag containing version number
   3. Push changes

   ```sh
   poetry version <VERSION>
   export icoapi_version="$(poetry version -s)"
   git commit -a -m "Release: Release version $icoapi_version"
   git tag "$icoapi_version"
   git push && git push --tags
   ```

5. Open the [release notes](https://github.com/MyTooliT/ICOapi/tree/main/doc/release) for the latest version and [create a new release](https://github.com/MyTooliT/ICOapi/releases/new)
   1. Paste them into the main text of the release web page
   2. Insert the version number into the tag field
   3. For the release title use “Version <VERSION>”, where `<VERSION>` specifies the version number (e.g. “Version 0.2”)
   4. Click on “Publish Release”

   **Note:** Alternatively you can also use the [`gh`](https://cli.github.com) command:

   ```sh
   gh release create
   ```

   to create the release notes.


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
http PUT 'http://localhost:33215/api/v1/sth/connect' mac_address='08-6B-D7-01-DE-81'
```

Check if the STU is connected to the sensor device:

```sh
http POST 'http://localhost:33215/api/v1/stu/connected' name='STU 1'
```

Disconnect from sensor device:

```sh
http PUT http://localhost:33215/api/v1/sth/disconnect
```
