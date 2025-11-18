# Python + Poetry + Fast startup
FROM python:3.12-slim

# Runtime env
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    POETRY_VIRTUALENVS_CREATE=false

# System deps + Poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl build-essential \
    && curl -sSL https://install.python-poetry.org | python3 - \
    && ln -s /root/.local/bin/poetry /usr/local/bin/poetry \
    && apt-get purge -y --auto-remove curl \
    && rm -rf /var/lib/apt/lists/*

# Workdir
WORKDIR /app

# App code
COPY . .

# Install deps (only main/runtime deps)
RUN poetry install --no-interaction --no-ansi --only main


# Port config (build-time default + runtime env)
ARG VITE_API_PORT=8000
ENV VITE_API_PORT=${VITE_API_PORT}

# Document the port
EXPOSE ${VITE_API_PORT}

# Run your app (Docker restart policy is set outside the Dockerfile)
CMD ["python3", "icoapi/api.py"]
