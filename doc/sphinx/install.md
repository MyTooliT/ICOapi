# Installation & Setup

This repository can be

- [setup manually](#manual-install),
- installed as a [system service on Linux-based](#system-service) systems or
- deployed using [Docker on **Linux-based** systems](#docker).

(manual-install)=

## Manual Install

### PyPI

To install the [latest released version of the package](https://pypi.org/project/icoapi/) you can use the command:

```sh
pip install icoapi
```

Afterwards you should be able to run the web API using the following command:

```sh
icoapi
```

### Repository

If you want to use the latest version of ICOapi (e.g. for development) then we recommend that you install:

- [`uv`](https://docs.astral.sh/uv/) and
- [`just`](https://just.systems).

After that please just use the command:

```sh
just run
```

to setup and start the web API.

(system-service)=

## System Service Installation (Linux)

For Linux, there is an installation script which sets the directory for the actual installation, the directory for the systemd service and the used systemd service name. The (sensible) defaults are:

```ini
SERVICE_NAME="icoapi"
INSTALL_DIR="/etc/icoapi"
SERVICE_PATH="/etc/systemd/system"
```

Run the script to install normally:

```sh
./install.sh
```

Or, if you want to delete existing installations and do a clean reinstall, add the `--force` flag:

```sh
./install.sh --force
```

(docker)=

## Docker (Linux)

You can use our [`Dockerfile`](../../Dockerfile) to build a [Docker](https://www.docker.com) image for the API:

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
