FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

ENV PYTHONUNBUFFERED 1

# [Optional] If your requirements rarely change, uncomment this section to add them to the image.
COPY requirements.txt /tmp/pip-tmp/
RUN pip3 --disable-pip-version-check --no-cache-dir install -r /tmp/pip-tmp/requirements.txt && rm -rf /tmp/pip-tmp

# Install additional OS packages needed for building native extensions
# (lupa requires LuaJIT dev headers; psycopg2-binary uses libpq).
RUN rm -f /etc/apt/sources.list.d/yarn.list \
    && apt-get update \
    && export DEBIAN_FRONTEND=noninteractive \
    && apt-get -y install --no-install-recommends \
        postgresql-client \
        build-essential \
        libpq-dev \
        libluajit-5.1-dev \
        pkg-config \
        librsvg2-bin \
    && rm -rf /var/lib/apt/lists/*
