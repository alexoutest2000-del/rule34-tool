# Rule34 Tool

Local web interface for searching, previewing, and selectively downloading images from rule34.xxx.

## Features

- **Web UI** — single-page app, no CLI needed
- **Tag search** — search by one or more tags
- **Thumbnail preview** — responsive grid with lazy loading
- **Selective download** — checkboxes, Select All/Deselect, progress tracking
- **Downloads to local directory** — `./downloads/` by default

## Quick Start

```bash
# 1. Clone
git clone git@github.com:alexoutest2000-del/rule34-tool.git
cd rule34-tool

# 2. Install
python3 -m venv .venv
.venv/bin/pip install flask requests tqdm pyyaml

# 3. Configure API credentials
mkdir -p ~/.config/rule34-tool
cat > ~/.config/rule34-tool/config.yaml << EOF
user_id: "YOUR_USER_ID"
api_key: "YOUR_API_KEY"
delay: 1.0
download_dir: "./downloads"
timeout: 30
EOF

# 4. Run
.venv/bin/python server.py
# Open http://localhost:8080
```

## Getting API Credentials

1. Create an account on [rule34.xxx](https://rule34.xxx)
2. Go to **Account → Options** → API Access Credentials
3. Copy your `user_id` and `api_key`

## Usage

1. Open `http://localhost:8080` in your browser
2. Enter tags (space-separated) in the search bar
3. Browse the thumbnail grid
4. Check the boxes for images you want
5. Click **Download Selected**
6. Files save to `./downloads/`

## Architecture

```
rule34-tool/
├── server.py           # Flask web server + single-page UI
├── rule34/
│   ├── api.py          # Rule34 API client (auth, search, pagination)
│   ├── config.py       # YAML config loader
│   └── cli.py          # Optional CLI (not the primary interface)
├── requirements.txt
└── .gitignore          # config.yaml, downloads/, .venv/ excluded
```

- **API key stays server-side** — never exposed to the browser
- **Rate limited** — 1 request/second to respect API limits
- **Static HTML UI** — dark theme, responsive grid, vanilla JS (no frameworks)

## Configuration

| Key | Default | Description |
|-----|---------|-------------|
| `user_id` | (required) | Rule34 account user ID |
| `api_key` | (required) | Rule34 API key |
| `delay` | `1.0` | Seconds between API calls |
| `download_dir` | `./downloads` | Where to save images |
| `timeout` | `30` | HTTP request timeout |

Config is loaded from `~/.config/rule34-tool/config.yaml` or environment variables (`RULE34_USER_ID`, `RULE34_API_KEY`, etc.).

## Security

- `config.yaml` is gitignored — credentials never committed
- API key loaded server-side only
- No authentication exposed to the browser
- Uses SSH for GitHub remote
- Downloads restricted to configured directory

## License

MIT
