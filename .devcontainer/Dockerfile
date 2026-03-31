FROM mcr.microsoft.com/devcontainers/python:1-3.11-bullseye

ENV PYTHONUNBUFFERED=1

# --------------------------------------------------------------------
# Base system dependencies
# --------------------------------------------------------------------
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
        wget \
        cmake \
        swig \
        libproj-dev \
        libgeos-dev \
        libsqlite3-dev \
        libexpat1-dev \
        libxml2-dev \
        libcurl4-openssl-dev \
        bison \
    && rm -rf /var/lib/apt/lists/*

# Ensure NumPy is available for the Python used by GDAL bindings (Python 3.11 in the base image).
RUN python3 -m pip install --no-cache-dir --upgrade pip \
    && python3 -m pip install --no-cache-dir numpy

# --------------------------------------------------------------------
# Build GDAL from source (vector-focused minimal build)
# --------------------------------------------------------------------
ARG GDAL_VERSION=3.12.2

RUN wget https://github.com/OSGeo/gdal/archive/refs/tags/v${GDAL_VERSION}.tar.gz -O /tmp/gdal.tar.gz \
    && mkdir /tmp/gdal-src \
    && tar -xzf /tmp/gdal.tar.gz -C /tmp/gdal-src --strip-components=1 \
    && cd /tmp/gdal-src \
    && mkdir build \
    && cd build \
    && cmake .. \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIBS=ON \
        -DBUILD_TESTING=OFF \
        -DGDAL_BUILD_OPTIONAL_DRIVERS=OFF \
        -DOGR_BUILD_OPTIONAL_DRIVERS=ON \
        -DOGR_ENABLE_DRIVER_S57=ON \
        -DGDAL_ENABLE_DRIVER_GTIFF=ON \
        -DGDAL_ENABLE_DRIVER_PNG=ON \
        -DGDAL_ENABLE_PYTHON=ON \
        -DOGR_ENABLE_DRIVER_PGDUMP=ON \
        -DOGR_ENABLE_DRIVER_PG=ON \
        -DPython3_EXECUTABLE=/usr/local/bin/python3 \
        -DPython3_FIND_STRATEGY=LOCATION \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    && cd / \
    && rm -rf /tmp/gdal-src /tmp/gdal.tar.gz