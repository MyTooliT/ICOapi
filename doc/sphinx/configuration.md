# Configuration

## Environment Variables

The application has sensible defaults for all environment variables.

Should you want to change those not via arguments but via files, you have three
chances to do so:

1. For local development: the `.env` file should be in the project root.
2. For normal usage, the file is in the user data directory (`user_data_dir`). The location of this directory depends on the used operating system (and is also part of the log output of the `icoapi` command):

   (user-data-directory)=

   | OS      | User Data Directory                        |
   | ------- | ------------------------------------------ |
   | Linux   | `$HOME/.local/share/ICOdaq`                |
   | macOS   | `$HOME/Library/Application Support/ICOdaq` |
   | Windows | `$HOME\AppData\Local\ICOdaq`               |

   **Note:** `$HOME` refers to the directory of the currently logged in user.

3. When no environment variable file was found, we check the bundle directory from the [PyInstaller](https://pyinstaller.org) for the bundled file.

> All variables prefixed with `VITE_` indicate that there is a counterpart in the client side environment variables. This is to show that changes here most likely need to be propagated to the client (and Electron wrapper, for that matter).

### Client/API Connection Settings

These settings determine all forms of client/API communication details.

The main REST API is versioned, does _NOT_ use SSL at the moment and has certain origins set as secure for CORS.

```ini
VITE_API_PROTOCOL=http
VITE_API_HOSTNAME="0.0.0.0"
VITE_API_PORT=33215
VITE_API_VERSION=v1
VITE_API_ORIGINS="http://localhost,http://localhost:5173,http://localhost:33215,http://127.0.0.1:5173"
```

The WebSocket is for streaming data. It only requires a `VITE_API_WS_PROTOCOL` variable akin to `VITE_API_PROTOCOL` which decides between SSL or not, and how many times per second the WebSocket should send data.

```ini
VITE_API_WS_PROTOCOL=ws
WEBSOCKET_UPDATE_RATE=300
```

### File Storage Settings

These settings determine where the measurement and configuration files are stored locally.

```ini
VITE_APPLICATION_FOLDER=ICOdaq
```

`VITE_APPLICATION_FOLDER` expects a single folder name and locates that folder under a certain path. We use the `user_data_dir()` from the package `platformdirs` to simplify this. The system always logs which folder is used for storage.

### Logging Settings

```ini
LOG_LEVEL=DEBUG
LOG_USE_JSON=0
LOG_USE_COLOR=1
LOG_PATH="C:\Users\breurather\AppData\Local\icodaq\logs"
LOG_MAX_BYTES=5242880
LOG_BACKUP_COUNT=5
LOG_NAME_WITHOUT_EXTENSION=icodaq
LOG_LEVEL_UVICORN=INFO
```

- `LOG_LEVEL` is one of:
  - `DEBUG`
  - `INFO`
  - `WARNING`
  - `ERROR`
  - `CRITICAL`

- `LOG_USE_JSON` formats the logs in plain JSON if set to `1`
  - useful for production logs

- `LOG_USE_COLOR` formats the logs in color if set to `1`
  - useful for local development in a terminal

- `LOG_PATH` overrides the default log location as an absolute path to a directory
  - You **need** to have write permissions
  - The defaults are:
    - Windows: `$HOME/AppData/Local/icodaq/logs`
    - Linux/macOS: `$HOME/.local/share/icodaq/logs`

- `LOG_NAME_WITHOUT_EXTENSION` sets the name of the logfile (without the file extension).

- `LOG_MAX_BYETS` and `LOG_BACKUP_COUNT` determine the maximum size and backup number of the logs.

- `LOG_LEVEL_UVICORN` controls the log level for the [uvicorn](https://uvicorn.dev/) web server.

## Configuration Files

The API currently works with 3 configuration files in the `.yaml` format:

- [`sensors.yaml`](config:sensors),
- [`metadata.yaml`](config:metadata),
- [`dataspace.yaml`](config:dataspace)

When the API web server starts, it checks for the availability of these files in the subfolder `config` of the [user data directory](#user-data-directory). If one of the config files does not exist, it is replaced by a copy from the default configuration files from the folder [`icoapi/config`](https://github.com/MyTooliT/ICOapi/tree/main/icoapi/config).

(config:configuration-file-header)=

### Configuration File Header

Each configuration file starts with a header (below the key `info`) containing information on the file and schema.

```yaml
info:
  schema_name: sensors_schema
  schema_version: 0.0.1
  config_name: General Purpose Sensor File
  config_date: "2025-10-07T13:52:40+0200"
  config_version: 0.0.1
```

The above section is exemplary for a sensor configuration file.

(config:sensors)=

### Sensor Configuration

ICOapi starts the measurement based on the selected measurement channels. It is up to the user to know which of the three measurement channels is connected to which sensor.

To make the channel selection easier, a layer of abstraction is present in this API and thus in the client and ICOdaq software package.

#### Structure

Within the `sensors.yaml` file, two separate areas (lists) exist:

1. Every element in the list below the key `sensors` contains [information about a specific sensor](#sensor-information).
2. The data below the key `sensor_configurations` maps a sensor channel (number) to one of the sensors (listed below the key `sensors`).

In addition to `sensors`, `sensor_configurations` (and the [header `info`](config:configuration-file-header)) a field for the default configuration, below the key `default_configuration_id`, exists. The file looks like this:

```yaml
info: ...

sensors:
  - ...
  - ...

sensor_configurations:
  - ...
  - ...

default_configuration_id:
```

(sensor-information)=

##### Sensors

Sensor information (which is also stored in the table `sensors` in the `*.hdf5` measurement file) looks like this:

```yaml
- name: Acceleration 100g
  offset: -125.0
  phys_max: 100.0
  phys_min: -100.0
  scaling_factor: 75.75757575757575 # Currently unused
  sensor_id: acc100g_01 # Used by API to identify sensor
  sensor_type: ADXL1001
  unit: g
  dimension: Acceleration
  volt_max: 2.97
  volt_min: 0.33
```

The example above defines values for the often used ±100g acceleration sensor in the x axis.

Note that the field `sensor_id` is what the API uses to identify the sensor for usage.

(sensor-configurations)=

##### Sensor Configurations

The sensor mapping determines which sensors and channels a user can select for measurement.

The data is structured as follows:

```yaml
- configuration_id: singleboard_GYRO
  configuration_name: GYRO
  channels:
    1: { sensor_id: acc100g_01 }
    6: { sensor_id: photo_01 }
    8: { sensor_id: gyro_01 }
    10: { sensor_id: vbat_01 }
```

- The `configuration_id` (`singleboard_GYRO` in our example) is what the client-side `.env` file can set to load as a default for tools.

- The `configuration_name` (`GYRO` in our example) is displayed to the client.

- The mapping of sensors follows the schema of `<channel>: { sensor_id: <sensor_id> }`.

##### Default Configuration

The `default_configuration_id` is set to one of the configuration ids (`configuration_id`) of the sensor configurations (e.g. something like `singleboard_GYRO` in the section [“Sensor Configurations”](#sensor-configurations)).

(config:metadata)=

### Metadata

To support the usage of arbitrary metadata when creating measurements, a
configuration system has been set up. This system starts as an Excel file in
which all metadata fields are defined. This file is then converted into a YAML
file (`metadata.yaml`).

The complete metadata logic can be found in the ICOweb repository.

The metadata is split into two parts:

- the metadata entered **before** a measurement starts (`pre_meta`)
- the metadata entered **after** the measurement has been ended (`post_meta`)

This ensures that common metadata like machine tool, process or cutting
parameters are set beforehand while keeping the option to require data after
the fact, such as pictures or tool breakage reports.

The pre-meta is sent with the measurement instructions while the post-meta is
communicated via the open measurement WebSocket.

(config:dataspace)=

### Dataspace

This file sets the dataspace connection settings if required. It simply holds
all the relevant information such as:

```yaml
connection:
  enabled: False
  username: myUser
  password: strongPw123!
  bucket: common
  bucket_folder: default
  protocol: https
  domain: trident.example.com
  base_path: api/v1
```

All relevant fields are strings without any `/` before or after the value. This
means that for the given example a complete endpoint would be:

`https://trident.example.com/api/v1/<endpoint>`

And the relevant storage would be in the folder `default` of the bucket
`common`.
