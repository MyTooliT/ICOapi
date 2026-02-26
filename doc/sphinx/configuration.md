# Configuration

## Environment Variables

The application has sensible defaults for all environment variables.

Should you want to change those not via arguments but via files, you have three
chances to do so:

1. For local development: the `.env` file should be in the project root.
2. For normal usage, the file is in the `user_data_dir`.
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
    - Windows: `AppData/Local/icodaq/logs`
    - Linux/macOS: `~/.local/share/icodaq/logs`

- `LOG_NAME_WITHOUT_EXTENSION` sets the name of the logfile (without the file extension).

- `LOG_MAX_BYETS` and `LOG_BACKUP_COUNT` determine the maximum size and backup number of the logs.

- `LOG_LEVEL_UVICORN` controls the log level for the [uvicorn](https://uvicorn.dev/) web server.
