# Development

## Tests

**Note:** Running the tests (successfully) requires that

- you connected a STU to your test system,
- at least one sensor device (e.g. STH) is available
- the sensor device has support for changing the sensor configuration (mapping sensor channels to measurement channels)

In the text below we assume that you installed

- [uv](https://docs.astral.sh/uv), and
- [just](https://github.com/casey/just)

To run the tests run the following command:

```sh
just test
```

Tests are grouped with [pytest markers](https://docs.pytest.org/en/stable/how-to/mark.html):

- `hardware`: tests that need the hardware described above. Run all other tests with `just test-no-hardware`.
- `mqtt`: tests that need an [MQTT](https://mqtt.org) broker. They are skipped, unless you set the environment variable `TEST_MQTT_BROKER` (host name of the broker). `TEST_MQTT_PORT` (default: 1883), `TEST_MQTT_USERNAME` and `TEST_MQTT_PASSWORD` are optional. The tests publish to topics below `icodaq-test/<random ID>` and remove what they published. Run only these tests with `just test-mqtt`, for example with a temporary [Mosquitto](https://mosquitto.org) broker:

  ```sh
  docker run -d --rm --name test-mosquitto -p 127.0.0.1:18883:1883 eclipse-mosquitto:2 \
    sh -c 'printf "listener 1883\nallow_anonymous true\n" > /tmp/m.conf && exec mosquitto -c /tmp/m.conf'
  TEST_MQTT_BROKER=127.0.0.1 TEST_MQTT_PORT=18883 just test-mqtt
  docker stop test-mosquitto
  ```

## Guidelines

These guidelines are a work-in-progress and aim to explain development decisions and support consistency.

### Logging

The application is set up to log _everything_. This is how the logging is set up.

#### Guidelines

- Log only after success
- Don’t log intent, like "Creating user..." or "Initializing widget..." unless it’s for debugging.
- Do log outcomes, like "User created successfully." — but only after the operation completes without error.
- Avoid logging in constructors unless they cannot fail
  - Prefer logging in methods that complete the actual operation,
  - or use a factory method to wrap creation and success logging.

#### Levels

| Action                            | Log Level            | Description (taken from [Python docs](https://docs.python.org/3/library/logging.html#logging-levels)) |
| --------------------------------- | -------------------- | ----------------------------------------------------------------------------------------------------- |
| Starting a process / intention    | `DEBUG`              | Detailed information for diagnosing problems. Mostly useful for developers.                           |
| Successfully completed action     | `INFO`               | For confirming that things are working as expected.                                                   |
| Recoverable error / edge case     | `WARNING`            | Indicates something unexpected happened or could cause problems later.                                |
| Expected failure / validation     | `ERROR`              | Used for serious problems that caused a function to fail.                                             |
| Critical Failure / unrecoverable  | `CRITICAL`           | For very serious errors. Indicates a critical condition — program may abort.                          |
| Unexpected exception (with trace) | `logger.exception()` | Serious errors, but the exception was caught.                                                         |

### Release

**Note:** In the text below we assume that you want to release version `<VERSION>` of the package. Please just replace this version number with the version that you want to release (e.g. `0.2.0`).

1. Make sure that all the checks and tests work correctly locally

   ```sh
   just
   ```

2. Make sure all [workflows of the CI system work correctly](https://github.com/MyTooliT/ICOapi/actions)

3. Release a new version on [PyPI](https://pypi.org/project/icoapi/):

   ```sh
   just release <VERSION>
   ```

4. Open the [release notes](https://github.com/MyTooliT/ICOapi/tree/main/doc/release) for the latest version and [create a new release](https://github.com/MyTooliT/ICOapi/releases/new)
   1. Paste them into the main text of the release web page
   2. Insert the version number into the tag field
   3. For the release title use “Version <VERSION>”, where `<VERSION>` specifies the version number (e.g. “Version 0.2”)
   4. Click on “Publish Release”

   **Note:** Alternatively you can also use the [`gh`](https://cli.github.com) command:

   ```sh
   gh release create
   ```

   to create the release notes.
