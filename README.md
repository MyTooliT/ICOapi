# ICOapi

This is a REST and WebSocket API using the python FastAPI library. You can find the official documentation [here](https://fastapi.tiangolo.com/).

Additionally, when the API is running, it hosts an OpenAPI compliant documentation under ``/docs``, e.g. under `localhost:8000/docs`.

## Install

Setup in an environment

```sh
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate
```

On linux:

```
./install_systemd
```

On windows:

```sh
pip install windows-curses==2.3.3
pip install -r requirements.txt
```

# Run

```sh
python3 api.py
```

 
