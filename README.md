# Flood Models Hamburg

Jupyter-Notebook, das für die Region Hamburg vier Modelle zum
Meeresspiegel-Anstieg aus digitalen Höhenmodellen (COP30, NASADEM) von
[OpenTopography](https://portal.opentopography.org/) berechnet und auf
einer interaktiven Karte visualisiert.

## Modelle

| Modell       | Bedeutung                                                    |
|--------------|--------------------------------------------------------------|
| Bathtub      | Alle Pixel ≤ Schwellwert (naiver „steigendes Wasser")        |
| Connected    | Nur Pixel mit Verbindung zum DEM-Rand (ozeanverbunden)       |
| Iterative    | Iterative Seed-Spread-Variante von Connected                |
| Flowtub      | Wasser fließt vom Meer aus, Deiche/Schwellen blockieren     |

## Schnellstart (empfohlen: uv)

```bash
# 1) uv installieren (einmalig)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2) Im Projektordner:
cd /Users/msc/Documents/Python/Jupyter/4-Models

# 3) Environment anlegen + alle Deps installieren (legt auch uv.lock an):
uv sync

# 4) JupyterLab mit dem richtigen Kernel starten:
uv run jupyter lab
```

Im Notebook: alle Zellen ausführen. Beim ersten Lauf wird nach dem
**OpenTopography API-Key** gefragt – falls du den nicht jedes Mal
eintippen willst, siehe unten.

## Alternative ohne uv (pip + venv)

Falls du lieber pip nutzt:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
jupyter lab
```

## OpenTopography API-Key

Das Notebook liest den Key **ausschließlich** aus der Umgebungsvariablen
`OPENTOPOGRAPHY_API_KEY`. Es gibt **keinen** im Quelltext hinterlegten
Fallback-Key mehr — der Key gehört nicht ins Repo.

Damit der Key dauerhaft gesetzt ist (Mac, zsh):

```bash
echo 'export OPENTOPOGRAPHY_API_KEY="<dein_key>"' >> ~/.zshenv
# danach neu anmelden oder:
source ~/.zshenv
```

`~/.zshenv` (nicht `.zshrc`) wird auch von GUI-gestarteten Apps wie
JupyterLab aus dem Dock/Finder geladen.

Auf **Render.com** wird der Key im Dashboard unter
*Environment → Environment Variables* gesetzt (`sync: false` in
`render.yaml` — wird also nicht aus dem Repo synchronisiert). Ohne
gesetzten Key bricht das Notebook beim Start mit einer klaren
Fehlermeldung ab, statt stillschweigend fehlzuschlagen.

## Projektstruktur

```
.
├── 4Models.ipynb            # Haupt-Notebook (alles drin)
├── pyproject.toml           # Abhängigkeiten (uv / pip kompatibel)
├── requirements.txt         # Gepinnte Deps für Render.com
├── Dockerfile               # Voilà-Container (Python 3.12)
├── voila.json               # Voilà-Konfiguration (theme, template)
├── render.yaml              # Render.com Blueprint
├── scripts/
│   └── upload_artifacts.py  # Lokal vorgerechnete Artefakte auf Webspace laden
├── README.md                # Diese Datei
├── dem-src/                 # Gecachte OpenTopography-DEMs (GeoTIFF)
└── flood-masks/             # Berechnete Überflutungsmasken (GeoTIFF)
```

## Deployment auf Render.com

Die App läuft als **Voilà-Webservice** in einem Docker-Container und ist
in 5–10 Minuten online.

**Voraussetzungen**
- Repo auf GitHub gepusht
- Kostenloser Account auf [render.com](https://render.com)

**Schritte**

1. Repo nach GitHub pushen.
2. Auf Render → **New +** → **Blueprint** → Repo verbinden.
3. Render erkennt `render.yaml` automatisch und legt den Service an.
4. Im Service-Dashboard unter **Environment**:
   - `OPENTOPOGRAPHY_API_KEY` als Secret setzen.
5. Auf **Manual Deploy** klicken – das Image wird gebaut (~3–6 min).
6. URL `https://<service>.onrender.com` öffnen.

**Hinweise zum Free-Tier**
- 512 MB RAM: reicht für Hamburg-BBOX und die 9 Wasserstufen; bei sehr
  großen BBOXen oder vielen Wasserstufen kann das knapp werden.
- Der Service schläft nach 15 min Inaktivität ein. Erster Request
  danach dauert ~30 s („Cold Start").
- Masken & DEMs werden **on-demand im Container** berechnet und leben
  nur in dessen Ephemeral Disk – bei jedem Redeploy sind sie weg.
  Für Persistenz: Volumes / Render Disks ergänzen (im Free-Tier
  nicht verfügbar).

## Konfiguration

Im Notebook (oben in der ersten Code-Zelle):

- `DEM_SOURCES` – welche DEMs geladen werden (`COP30`, `NASADEM`)
- `BBOX`       – Bounding Box (Default: Hamburg/Norddeutsche Küste)
- `WATER_LEVELS` – Liste der Meeresspiegel-Anstiege in Metern
- `MODELS`     – Colormap + Label der vier Modelle
- `REMOTE_BASE_URL` – URL zum Remote-Cache (z. B. eigener Webspace)

## Persistente Masken über eigenen Webspace

Render-Free hat keinen Persistent Disk. Die Erstberechnung der Masken
dauert je nach BBOX und Wasserstufen-Anzahl Minuten bis Stunden. Um
beim Deployment sofort starten zu können, wird ein externer Cache
verwendet – z. B. ein normaler Webspace, auf dem die GeoTIFFs liegen.

**Workflow einmalig lokal**

1. `4Models.ipynb` lokal komplett ausführen – dabei landen alle Masken
   unter `flood-masks/` und DEMs unter `dem-src/`.
2. Artefakte auf den Webspace laden:
   ```bash
   # mit rsync (am einfachsten):
   python scripts/upload_artifacts.py \
       --protocol rsync \
       --rsync-target user@webspace.example.de:/path/to/flood-models

   # oder mit SFTP:
   python scripts/upload_artifacts.py \
       --protocol sftp \
       --host webspace.example.de \
       --user u12345 \
       --password "$WEBSPACE_PASSWORD" \
       --remote-dir /flood-models

   # oder mit FTP:
   python scripts/upload_artifacts.py \
       --protocol ftp --host ftp.example.de ...
   ```
   Das Skript erzeugt automatisch ein `manifest.json` mit SHA256-Hashes.

**Auf Render**: Env-Variable setzen
```
FLOOD_REMOTE_BASE_URL=https://dein-space.de/flood-models
```

Beim Start prüft das Notebook für jedes fehlende Artefakt, ob es unter
`$FLOOD_REMOTE_BASE_URL/<pfad>` verfügbar ist, und lädt es bei Bedarf
nach. Erst wenn dort auch nichts ist, wird lokal berechnet.

**Reihenfolge im Code** (pro Artefakt):
1. Datei liegt lokal vor → verwenden
2. Datei fehlt lokal, aber auf Remote → herunterladen
3. Weder lokal noch remote → selbst berechnen

**Vorteile**
- Auf Render: Startzeit sinkt von „Stunden" auf „Sekunden" (Cache-Warm).
- Du behältst die Hoheit über deine Daten (kein Cloud-Speicher nötig).
- Bei jedem neuen Wasserstand: lokal rechnen, neu hochladen,
  Render macht beim nächsten Deploy den Rest.

## Reproduzierbare Builds

`uv sync` legt eine `uv.lock` an, die jede transitive Abhängigkeit
pinnt. Diese Datei mit ins Repo committen – andere erhalten dadurch
**exakt** dieselben Versionen.

```bash
git add pyproject.toml uv.lock
```

## Lizenz

MIT
