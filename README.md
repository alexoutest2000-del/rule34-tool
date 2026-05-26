# Rule34 Tool

Local web interface and CLI for searching, previewing, and selectively downloading images from [rule34.xxx](https://rule34.xxx).

## Features

**Web UI**
- Single-page dark-themed gallery — open `http://localhost:8080` in your browser
- Tag search with thumbnail grid and lazy loading
- Selective download: checkboxes, Select All/Deselect, progress bar
- Files saved to `./downloads/` (or your configured path)

**CLI** (`r34`)
- `r34 search <tags>` — list results in terminal
- `r34 preview <tags>` — generate an HTML gallery and open it in your browser
- `r34 download <tags>` — bulk download images by tag
- `r34 download --ids 123,456,789` — download specific post IDs
- `r34 config` — show or set API credentials

**Reliability**
- Rate-limited (1 req/s default) to respect API limits
- Skips already-downloaded files (idempotent — safe to re-run)
- Progress tracking in both web UI and CLI

## Setup

### 1. Clone and install

```bash
git clone git@github.com:alexoutest2000-del/rule34-tool.git
cd rule34-tool

python3 -m venv .venv
.venv/bin/pip install flask requests tqdm pyyaml
```

### 2. Get API credentials

1. Create an account at [rule34.xxx](https://rule34.xxx)
2. Go to **Account → Options** → **API Access Credentials**
3. Copy your `user_id` and `api_key`

### 3. Configure

```bash
mkdir -p ~/.config/rule34-tool
cat > ~/.config/rule34-tool/config.yaml << 'EOF'
user_id: "YOUR_USER_ID"
api_key: "YOUR_API_KEY"
delay: 1.0
download_dir: "./downloads"
timeout: 30
EOF
```

Or use the interactive CLI setup:
```bash
.venv/bin/python -m rule34.cli config set
```

Or set environment variables:
```bash
export RULE34_USER_ID="..."
export RULE34_API_KEY="..."
```

## Usage

### Web UI (recommended for browsing)

```bash
.venv/bin/python server.py
# Open http://localhost:8080
```

1. Enter tags in the search bar (space-separated for multiple tags)
2. Browse the thumbnail grid
3. Check images you want
4. Click **Download Selected** — progress shown in the bottom bar
5. Files appear in `./downloads/`

### CLI — Search

```bash
# List first 20 results in terminal
r34 search anime_girl solo

# Increase limit (max 1000 per page)
r34 search -n 200 anime_girl solo

# Combine tags (AND by default)
r34 search -n 50 blonde_hair blue_eyes 1girl
```

### CLI — Preview gallery

```bash
# Opens HTML gallery in your browser
r34 preview blonde_hair solo

# Paginate through more results automatically
r34 preview -m 500 blonde_hair solo

# Save gallery to a specific file, don't open browser
r34 preview -o my_gallery.html -n 100 blonde_hair solo --no-open
```

### CLI — Download

```bash
# Download all images matching tags (up to 100 by default)
r34 download blonde_hair solo

# Download specific post IDs
r34 download --ids 12345,67890,11111

# Paginate deeper — download up to 500 matching images
r34 download -m 500 -o ./my_downloads/ blonde_hair solo

# Resume: re-running skips already-downloaded files
r34 download anime_girl  # safe to re-run
```

### CLI — Config

```bash
# Show current config (api_key partially masked)
r34 config

# Interactive credential setup
r34 config set
```

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `user_id` | (required) | Rule34 account user ID |
| `api_key` | (required) | Rule34 API key |
| `delay` | `1.0` | Seconds between API calls |
| `download_dir` | `./downloads` | Where to save images |
| `timeout` | `30` | HTTP request timeout (seconds) |

Config is loaded from `~/.config/rule34-tool/config.yaml`. Environment variables (`RULE34_USER_ID`, `RULE34_API_KEY`, etc.) override file values.

## Architecture

```
rule34-tool/
├── server.py              # Flask web server + single-page UI
├── run.sh                 # Quick launcher (venv + server)
├── rule34/
│   ├── api.py             # Rule34 API client (search, pagination, rate limiting)
│   ├── config.py           # YAML config loader with env var fallback
│   ├── cli.py              # CLI entrypoint (search, preview, download, config)
│   └── preview.py          # Standalone HTML gallery generator
├── requirements.txt
└── .gitignore             # config.yaml, downloads/, .venv/ excluded
```

**API key stays server-side** — never exposed to the browser. All API calls go through the Flask backend.

## Security

- `config.yaml` is gitignored — credentials never end up in source control
- API key loaded server-side only; browser only sees image URLs and post metadata
- Downloads restricted to the configured directory
- Uses SSH for GitHub remote (no plaintext credentials in remotes)

## Running on a remote server

To access the web UI on a remote machine:

```bash
# On the server — bind to all interfaces
python server.py --host 0.0.0.0 --port 8080

# On your local machine — SSH tunnel
ssh -L 8080:localhost:8080 user@your-server
# Then open http://localhost:8080 in your browser
```

## Troubleshooting

**"API credentials not configured" error**
Create `~/.config/rule34-tool/config.yaml` with your `user_id` and `api_key`. See [Getting API Credentials](#getting-api-credentials) above.

**Rate limiting / slow downloads**
Increase `delay` in config (e.g., `2.0` for 0.5 req/s) or reduce batch sizes with `--limit` / `--max-results` flags.

**Skipped files**
The downloader skips files that already exist in the output directory. To re-download a specific file, delete it first.