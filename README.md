# Rule34 Tool

Local web interface for searching, previewing, and downloading images from [rule34.xxx](https://rule34.xxx).

## Setup

```bash
git clone git@github.com:alexoutest2000-del/rule34-tool.git
cd rule34-tool

python3 -m venv .venv
.venv/bin/pip install flask requests tqdm pyyaml

# Run
.venv/bin/python server.py
# Open http://localhost:8010
```

**First run**: Click the ⚙ icon in the top bar and paste your rule34 credentials in the format:

```
&api_key=YOUR_API_KEY&user_id=YOUR_USER_ID
```

Get this string from your rule34.xxx account: **Account → Options → API Access Credentials**.

Credentials are stored in `~/.config/rule34-tool/config.yaml` (gitignored — never committed).

## Usage

### Search

1. Enter tags in the search bar (space-separated)
2. Click **Search** or press Enter
3. Results appear as thumbnails in a grid

### Select and download

1. Click images to select them (or use **All** / **None** buttons)
2. Click **⬇** in the top bar or the bottom bar to download
3. Progress shown in the bottom bar — files saved to `./downloads/`
4. Already-downloaded files are skipped automatically (safe to re-run)

### Downloads tab

Click **📁 Downloads** to see all downloaded files with sizes. From there you can:
- Select and delete files
- Bulk delete with **Delete Selected**
- See total count and size

### Settings

Click **⚙** to open settings:
- **API Credentials** — paste the full `&api_key=...&user_id=...` string
- **API Delay** — seconds between requests (default: 1.0)
- **HTTP Timeout** — seconds before a request times out (default: 30)
- **Download Directory** — where images are saved

## Architecture

```
rule34-tool/
├── server.py              # Flask web server + single-page UI
├── run.sh                 # Quick launcher
├── rule34/
│   ├── api.py             # Rule34 API client (search, pagination)
│   ├── config.py          # YAML config loader (credentials format)
│   ├── cli.py             # CLI (search, preview, download — optional)
│   └── preview.py         # Standalone HTML gallery generator
├── requirements.txt
└── .gitignore             # config.yaml, downloads/, .venv/ excluded
```

## Remote access

To access the UI on a remote server:

```bash
# On the server
python server.py

# On your local machine — SSH tunnel
ssh -L 8010:localhost:8010 user@your-server
# Open http://localhost:8010
```

## Troubleshooting

**"API not configured" warning** — Click ⚙ and paste your credentials.

**Empty search results** — Check that your credentials are correct. The header shows 🔞 when configured, 🔞⚠ when not.

**Slow downloads** — Increase the API delay in ⚙ settings to reduce server load.