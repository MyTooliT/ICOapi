FROM python:3.13-slim-bookworm
COPY --from=docker.io/astral/uv:latest /uv /uvx /bin/

WORKDIR /app

COPY . .

RUN uv venv
RUN uv sync

ENV VITE_API_PORT=33215

EXPOSE 33215

CMD ["uv", "run", "icoapi"]