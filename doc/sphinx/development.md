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

2. Make sure all [workflows of the CI system work correctly](https://github.com/MyTooliT/Cleaned-ICOapi/actions)

3. Release a new version on [PyPI](https://pypi.org/project/icoapi/):

   ```sh
   just release <VERSION>
   ```

4. Open the [release notes](https://github.com/MyTooliT/Cleaned-ICOapi/tree/main/doc/release) for the latest version and [create a new release](https://github.com/MyTooliT/Cleaned-ICOapi/releases/new)
   1. Paste them into the main text of the release web page
   2. Insert the version number into the tag field
   3. For the release title use “Version <VERSION>”, where `<VERSION>` specifies the version number (e.g. “Version 0.2”)
   4. Click on “Publish Release”

   **Note:** Alternatively you can also use the [`gh`](https://cli.github.com) command:

   ```sh
   gh release create
   ```

   to create the release notes.
