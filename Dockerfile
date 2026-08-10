# ============================================================================
# Voilà + Flood Models Hamburg – Render.com Image
# Python 3.12 (sicher & kompatibel zu allen aktuellen Wheels: rasterio,
# leafmap 0.61, Voila 0.5.12).
# ============================================================================

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Voila liest diese Variable, um zu wissen wo /voila/sync liegt.
    JUPYTER_PATH=/usr/local/share/jupyter

# GDAL/GEOS für rasterio, fiona, geopandas (Debian wheels).
# libgomp / libstdc++ sind als Laufzeit-Deps für numpy/scipy nötig.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        gdal-bin \
        libgdal-dev \
        libgeos-dev \
        libproj-dev \
        libgomp1 \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# GDAL_VERSION muss zum installierten gdal-bin passen -> dann holt pip
# die passenden rasterio/fiona Wheels von PyPI (manylinux).
ENV GDAL_VERSION=$(gdal-config --version)

WORKDIR /app

# Erst Requirements kopieren -> Docker-Layer-Caching für pip install
COPY requirements.txt ./requirements.txt

# Install in zwei Schichten:
#   1) schwere native Deps (rasterio, fiona, geopandas) – selten geändert
#   2) leichte Jupyter/Voilà/leafmap-Deps – häufiger geändert
RUN pip install --no-cache-dir \
        "rasterio>=1.3.10" \
        "fiona>=1.9" \
        "geopandas>=1.0" \
        "shapely>=2.0" \
        "scipy>=1.11" \
        "numpy>=1.26" \
        "requests>=2.32" \
        "rioxarray>=0.15" \
        "pysheds>=0.4" \
    && pip install --no-cache-dir \
        "leafmap[raster]>=0.30" \
        "ipywidgets>=8.1" \
        "voila>=0.5.10" \
        "jupyterlab>=4.2" \
        "ipykernel>=6.29"

# Jetzt erst das Notebook + Helper-Files
COPY 4Models.ipynb ./
COPY voila.json ./voila.json

# Voilà rendert standardmäßig auf 0.0.0.0:8866 – Render erwartet PORT.
ENV VOILA_PORT=8866
ENV VOILA_HOST=0.0.0.0
EXPOSE 8866

# Health-Check (Render schaut auf den Port, nicht auf /health – aber schadet nicht)
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fsS "http://localhost:${VOILA_PORT}/voila" || exit 1

# Entrypoint: Notebook ausführen. Render setzt $PORT – wird respektiert.
CMD ["sh", "-c", "voila 4Models.ipynb \
        --port=${PORT:-8866} \
        --host=0.0.0.0 \
        --Voila.ip=${VOILA_HOST} \
        --Voila.log_level=INFO \
        --no-browser \
        --strip_sources=True"]
