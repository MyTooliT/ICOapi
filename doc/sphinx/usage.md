# Usage

The example commands below use the [command line version of httpie](https://httpie.io/cli). For more information on the specific endpoints, please take a look at the documentation which should be available under the endpoint `/docs`, e.g. [`localhost:33215/docs`](http://localhost:33215/docs), after [you installed and setup](install:installation-and-setup) ICOapi.

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
