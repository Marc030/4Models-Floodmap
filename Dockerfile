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
# python:3.12-slim (Debian bookworm) liefert GDAL 3.10.x.
ENV GDAL_VERSION=3.10.0

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

# Health-Check: testet NUR "Voilà lauscht und antwortet", nicht "Notebook
# ist fertig gerendert". Der Render-Endpoint (/voila/render/4Models.ipynb)
# braucht beim Cold-Start 60–90 s (DEM laden) und würde den Check immer
# rot machen. Stattdessen fragen wir Voilà's Landingpage ab – die ist
# immer sofort 200, sobald der Server läuft.
#   -sS         : silent, aber zeige Fehler
#   -o /dev/null: Response-Body verwerfen
#   -w "%{http_code}": nur den Statuscode ausgeben
#   - grep 200  : Exit 0 nur bei 200; alles andere (4xx/5xx/Timeout) → 1
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD curl -sS -o /dev/null -w "%{http_code}" "http://localhost:${PORT:-8866}/voila" | grep -q "^200$" || exit 1

# Entrypoint: Notebook ausführen. Render setzt $PORT – wird respektiert.
# Offizielles Pattern aus Voilà-Doku für Container-Deploys:
#   --port=$PORT  --Voila.ip=0.0.0.0  --no-browser
# strip_sources ist Default in Voilà 0.5, muss nicht gesetzt werden.
# Ohne --Voila.base_url mounted Voilà das Notebook unter /voila/render/<name>,
# und der Static-Files-Handler findet das .ipynb direkt im Working Directory.
CMD ["sh", "-c", "exec voila 4Models.ipynb \
        --port=${PORT:-8866} \
        --Voila.ip=0.0.0.0 \
        --no-browser \
        --Voila.log_level=INFO"]
