# ICOapi

A REST and WebSocket API using the Python FastAPI library. You can find the official documentation [here](https://fastapi.tiangolo.com/).

We currently support Windows 10+ and Debian/Linux.

Additionally, when the API is running, it hosts an OpenAPI compliant documentation under ``/docs``, e.g. under `localhost:8000/docs`.

# Installation

This repository can be setup manually for Windows and Linux or using the installation script for Linux.

## Prerequisites

- Python 3.10+, from the official [Python Website](https://www.python.org/downloads/)

## Manual Installation (Development)

For a Linux environment:
```sh
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

On Windows, also include this dependency:
```sh
pip install windows-curses==2.3.3
```

## Service Installation (Linux)

For Linux, there is an installation script which sets the directory for the actual installation, the directory for the 
systemd service and the used systemd service name. The (sensible) defaults are:

```
SERVICE_NAME="icoapi"
INSTALL_DIR="/etc/icoapi"
SERVICE_PATH="/etc/systemd/system"
```

After checking, run the script to install normally:

```sh
./install
```

Or, if you want to delete existing installations and do a clean reinstall, add the `--force` flag:

```sh
./install --force
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
VITE_BACKEND_MEASUREMENT_DIR=icogui
# OR
VITE_BACKEND_FULL_MEASUREMENT_PATH=C:\Users\breurather\AppData\Local\icogui
```

`VITE_BACKEND_MEASUREMENT_DIR` expects a single folder name and locates that folder under a certain path
- On Windows, that path is `%LocalAppData%`
- On Linux, it is the first available of:
  - `$XDG_DATA_DIRS`
  - `"/usr/local/share:/usr/share"`

`VITE_BACKEND_FULL_MEASUREMENT_PATH` lets you override the default pathing and tries to create the folder at your 
supplied location. 
- Use this at your own discretion as not having a writable directory for measurements will crash the program.
- This is unfortunately not OS-agnostic for now.

### Trident Data Storage Settings

These settings control the implementation of the Trident API to use as a connected data storage. It requires credentials
and needs to be explicitly enabled by setting the `TRIDENT_API_ENABLED` to `True`

```
TRIDENT_API_ENABLED=True
TRIDENT_API_USERNAME=...
TRIDENT_API_PASSWORD=...
TRIDENT_API_BUCKET="ctd-data-storage"
TRIDENT_API_BASE_URL="https://iot.ift.tuwien.ac.at/trident"
```

## Metadata Type/Class Generation

To support the usage of arbitrary metadata when creating measurements, a configuration system has been set up. This 
system starts as en Excel file in which all metadata fields are defined. This file is then parsed into a YAML file, from
which it can be used further.

In the case of this API, we want to generate the Python classes for type annotation from this configuration file. This
is especially important as the openAPI specification parses the type annotation and the client requires it to generate 
its own typing.

> This means that the typing on the client side is dependent on the generated types in this repository. While that may 
> not be perfect, the alternative would be to create both applications' types separately and risk inconsistencies.

To run the YAML file parsing, run the following script from the base directory of the repository:

```shell
cd utils
python3 generate_metadata.py
```

This will look for the ``.yaml`` file in `../icoclient/public/config` folder, which for development, one usually also 
has cloned to their local machine in the same directory as this repository. It will put the generated types under 
`models/autogen/metadata.py`. For customization, run:

```shell
cd utils
python3 generate_metadata.py --input <input_path> --output <output_path>
```

# Run

On Linux, if the installation script was used, the service runs automatically - but as-is, without any updates on 
changes to the repository as the service simply installs the current version.

For any other usage or for local development, run:

```shell
python3 api.py
```

 
