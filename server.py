#!/usr/bin/env python3
"""rule34-tool — Local web interface for searching and downloading from rule34.xxx.

Run:   python server.py
Then:  http://localhost:8010
"""

import os
import threading
import time
import zipfile
import io
from pathlib import Path
from flask import Flask, request, jsonify, send_file, render_template_string

from rule34.api import Rule34API, Post
from rule34.config import Config

app = Flask(__name__)

# Global state
api: Rule34API | None = None
cfg: Config | None = None
download_dir: Path = Path("./downloads")
download_lock = threading.Lock()
download_progress: dict = {}  # {download_id: {...}}


# ─── Config / Init ────────────────────────────────────────────

def load_config():
    global api, cfg, download_dir
    cfg = Config.load()
    assert cfg is not None, "Config.load() returned None"
    download_dir = Path(cfg.download_dir).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)
    if cfg.has_credentials:
        api = Rule34API(
            user_id=cfg.user_id,
            api_key=cfg.api_key,
            delay=cfg.delay,
            timeout=cfg.timeout,
        )
    else:
        api = None


def reinit_api():
    global api, cfg
    if cfg.has_credentials:
        api = Rule34API(
            user_id=cfg.user_id,
            api_key=cfg.api_key,
            delay=cfg.delay,
            timeout=cfg.timeout,
        )


# ─── API Endpoints ────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    """Return current configuration and API status."""
    return jsonify({
        "configured": cfg.has_credentials if cfg else False,
        "user_id": cfg.user_id[-4:] if cfg and cfg.user_id else "",
        "api_key_masked": ("*" * 20) + cfg.api_key[-4:] if cfg and cfg.api_key else "",
        "download_dir": str(download_dir) if download_dir else "",
        "delay": cfg.delay if cfg else 1.0,
        "timeout": cfg.timeout if cfg else 30,
        "download_count": len(list(download_dir.iterdir())) if download_dir.exists() and download_dir.is_dir() else 0,
        "download_size_mb": round(sum(f.stat().st_size for f in download_dir.rglob("*") if f.is_file()) / 1024 / 1024, 1) if download_dir.exists() else 0,
    })


@app.route("/api/config", methods=["POST"])
def api_set_config():
    """Save credentials and/or other settings. Re-init API if credentials changed."""
    global cfg
    data = request.get_json(force=True)

    if "credentials" in data:
        cfg.credentials = data["credentials"].strip()
        cfg._parse_credentials()
        cfg.save()
        reinit_api()

    if "delay" in data:
        cfg.delay = float(data["delay"])
        cfg.save()
        reinit_api()

    if "timeout" in data:
        cfg.timeout = int(data["timeout"])
        cfg.save()

    if "download_dir" in data:
        cfg.download_dir = data["download_dir"].strip()
        cfg.save()
        global download_dir
        download_dir = Path(cfg.download_dir).resolve()
        download_dir.mkdir(parents=True, exist_ok=True)

    return jsonify({"ok": True, "configured": cfg.has_credentials})


@app.route("/api/search")
def api_search():
    if not api:
        return jsonify({"error": "API not configured. Set credentials in Settings."}), 400
    tags = request.args.get("tags", "").strip()
    limit = request.args.get("limit", 50, type=int)
    page = request.args.get("page", 0, type=int)

    if not tags:
        return jsonify({"error": "No tags provided"}), 400

    try:
        posts = api.search(tags.split(), limit=min(limit, 1000), page=page)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify([{
        "id": p.id, "tags": p.tag_list, "preview_url": p.preview_url,
        "sample_url": p.sample_url, "file_url": p.file_url,
        "width": p.width, "height": p.height, "rating": p.rating,
        "score": p.score, "filename": p.filename, "ext": p.ext,
    } for p in posts])


@app.route("/api/search_all")
def api_search_all():
    if not api:
        return jsonify({"error": "API not configured. Set credentials in Settings."}), 400
    tags = request.args.get("tags", "").strip()
    max_results = request.args.get("max", 200, type=int)

    if not tags:
        return jsonify({"error": "No tags provided"}), 400

    try:
        posts = api.search_all(tags.split(), max_results=min(max_results, 5000))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify([{
        "id": p.id, "tags": p.tag_list, "preview_url": p.preview_url,
        "sample_url": p.sample_url, "file_url": p.file_url,
        "width": p.width, "height": p.height, "rating": p.rating,
        "score": p.score, "filename": p.filename, "ext": p.ext,
    } for p in posts])


@app.route("/api/download", methods=["POST"])
def api_download():
    data = request.get_json(force=True)
    ids = data.get("ids", [])
    if not ids:
        return jsonify({"error": "No IDs provided"}), 400

    download_id = f"dl_{int(time.time())}"
    download_progress[download_id] = {
        "total": len(ids), "done": 0, "failed": 0, "skipped": 0,
        "status": "starting", "files": [],
    }

    def do_download():
        import requests as req
        for i, pid in enumerate(ids):
            try:
                post = api.get_post(pid)
                if not post:
                    download_progress[download_id]["failed"] += 1
                    continue
                dest = download_dir / post.filename
                if dest.exists():
                    download_progress[download_id]["skipped"] += 1
                else:
                    resp = req.get(post.file_url, timeout=cfg.timeout, stream=True)
                    resp.raise_for_status()
                    with open(dest, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=8192):
                            f.write(chunk)
                download_progress[download_id]["done"] += 1
                download_progress[download_id]["files"].append(str(dest))
            except Exception as e:
                download_progress[download_id]["failed"] += 1
                download_progress[download_id]["files"].append(f"ERROR:{pid}:{e}")
        download_progress[download_id]["status"] = "complete"

    thread = threading.Thread(target=do_download, daemon=True)
    thread.start()
    return jsonify({"download_id": download_id})


@app.route("/api/download/<download_id>")
def api_download_status(download_id):
    prog = download_progress.get(download_id)
    if not prog:
        return jsonify({"error": "Unknown download"}), 404
    return jsonify(prog)


@app.route("/api/download/<download_id>/zip")
def api_download_zip(download_id):
    prog = download_progress.get(download_id)
    if not prog:
        return jsonify({"error": "Unknown download"}), 404
    if prog.get("status") != "complete":
        return jsonify({"error": "Download not yet complete"}), 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for fpath in prog.get("files", []):
            if fpath.startswith("ERROR:"):
                continue
            p = Path(fpath)
            if p.exists():
                zf.write(p, p.name)
    buf.seek(0)
    return send_file(
        buf, mimetype="application/zip", as_attachment=True,
        download_name=f"rule34_download_{download_id}.zip",
    )


@app.route("/api/files")
def api_files():
    """List downloaded files with sizes."""
    files = []
    if download_dir.exists():
        for f in sorted(download_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                files.append({
                    "name": f.name,
                    "size": f.stat().st_size,
                    "modified": int(f.stat().st_mtime),
                })
    return jsonify({"files": files, "total": len(files)})


@app.route("/api/files/<path:filename>", methods=["DELETE"])
def api_delete_file(filename):
    """Delete a downloaded file."""
    fpath = download_dir / filename
    if not fpath.exists() or not fpath.is_file():
        return jsonify({"error": "Not found"}), 404
    fpath.unlink()
    return jsonify({"ok": True})


@app.route("/api/files/delete_batch", methods=["POST"])
def api_delete_batch():
    """Delete multiple files by name."""
    data = request.get_json(force=True)
    names = data.get("names", [])
    deleted = []
    for name in names:
        fpath = download_dir / name
        if fpath.exists() and fpath.is_file():
            fpath.unlink()
            deleted.append(name)
    return jsonify({"deleted": len(deleted)})


@app.route("/api/tags")
def api_tag_suggestions():
    """Return tag autocomplete suggestions."""
    if not api:
        return jsonify([])
    prefix = request.args.get("q", "").strip()
    if not prefix or len(prefix) < 2:
        return jsonify([])
    try:
        suggestions = api.tag_suggestions(prefix, limit=12)
    except Exception:
        suggestions = []
    return jsonify(suggestions)


# ─── UI ───────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rule34 Tool</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #f5ede0; color: #2a1f10;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh; display: flex; flex-direction: column;
    padding-bottom: 80px;
}
/* ── Topbar ── */
.topbar {
    position: sticky; top: 0; z-index: 100;
    background: #f0e6d4ee; backdrop-filter: blur(12px);
    border-bottom: 1px solid #d4c4a8;
    padding: 12px 20px;
    display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
}
.topbar h1 { font-size: 1rem; color: #3a2a10; margin-right: 6px; white-space: nowrap; }
.topbar input[type="number"] { width: 70px; }

/* ── Tag input ── */
.tag-area {
    flex: 1; min-width: 220px; display: flex; flex-wrap: wrap; gap: 6px;
    padding: 8px 10px; border: 1px solid #c8b488; border-radius: 8px;
    background: #fff; min-height: 42px; align-items: center;
    cursor: text; transition: border-color 0.15s;
}
.tag-area:focus-within { border-color: #c87c2e; }
.tag-area input {
    border: none; background: transparent; outline: none;
    font-size: 0.9rem; color: #2a1f10; min-width: 120px; flex: 1;
    padding: 2px;
}
.tag-chip {
    display: flex; align-items: center; gap: 4px;
    background: #f0e6d4; border: 1px solid #d4c4a8; border-radius: 20px;
    padding: 3px 8px 3px 10px; font-size: 0.78rem; color: #5a4030;
    white-space: nowrap; max-width: 160px;
}
.tag-chip span { overflow: hidden; text-overflow: ellipsis; }
.tag-chip .remove-tag {
    cursor: pointer; color: #a89060; font-size: 0.85rem; line-height: 1;
    padding: 0 1px;
}
.tag-chip .remove-tag:hover { color: #c83020; }

/* ── Autocomplete ── */
.autocomplete-wrap { position: relative; }
.tag-suggestions {
    position: absolute; top: 100%; left: 0; right: 0; z-index: 300;
    background: #fff; border: 1px solid #c8b488; border-radius: 8px;
    box-shadow: 0 4px 16px #00000022; max-height: 220px; overflow-y: auto;
    display: none; margin-top: 4px;
}
.tag-suggestions.open { display: block; }
.tag-suggestion {
    padding: 8px 14px; font-size: 0.85rem; color: #5a4030;
    cursor: pointer; transition: background 0.1s;
}
.tag-suggestion:hover, .tag-suggestion.highlighted { background: #f0e6d4; }

/* ── Topbar buttons ── */
.topbar button {
    padding: 9px 18px; border: 1px solid #c8b488; border-radius: 8px;
    background: #fff; color: #5a4030; cursor: pointer;
    font-size: 0.88rem; transition: all 0.15s; white-space: nowrap;
}
.topbar button:hover { background: #f0e6d4; border-color: #a89060; }
.topbar button.primary { background: #c87c2e; border-color: #c87c2e; color: #fff; font-size: 0.95rem; padding: 10px 24px; font-weight: 600; }
.topbar button.primary:hover { background: #a86820; }
.topbar button.icon-btn { padding: 9px 14px; font-size: 1rem; }
.topbar button.active { background: #c87c2e; border-color: #c87c2e; color: #fff; }
.topbar button:disabled { opacity: 0.5; cursor: not-allowed; }

/* ── Download bar ── */
.download-bar {
    display: flex; align-items: center; gap: 14px; padding: 10px 20px;
    background: #fff; border-bottom: 1px solid #d4c4a8;
    flex-wrap: wrap;
}
.download-bar.hidden { display: none; }
.download-bar .dl-count { font-size: 0.85rem; color: #5a4030; white-space: nowrap; }
.download-bar .dl-count strong { color: #c87c2e; font-size: 1rem; }
.dl-progress-wrap { flex: 1; min-width: 160px; display: flex; align-items: center; gap: 10px; }
.dl-progress-bar { flex: 1; height: 8px; background: #d4c4a8; border-radius: 4px; overflow: hidden; }
.dl-progress-fill { height: 100%; background: #c87c2e; border-radius: 4px; transition: width 0.4s; width: 0%; }
.dl-progress-text { font-size: 0.78rem; color: #8a7050; white-space: nowrap; min-width: 60px; }
.download-bar button { font-size: 0.88rem; }

/* ── Tabs ── */
.tabs {
    display: flex; padding: 0 20px; gap: 0;
    background: #f5ede0; border-bottom: 1px solid #d4c4a8;
}
.tab {
    padding: 10px 20px; cursor: pointer; font-size: 0.88rem;
    color: #8a7050; border-bottom: 2px solid transparent;
    transition: all 0.15s;
}
.tab:hover { color: #5a4030; }
.tab.active { color: #c87c2e; border-bottom-color: #c87c2e; }

/* ── Panels ── */
.panel { display: none; flex: 1; }
.panel.active { display: flex; flex-direction: column; }

/* ── Status bar ── */
.status-bar {
    padding: 8px 20px; font-size: 0.78rem; color: #8a7050;
    border-bottom: 1px solid #d4c4a8; min-height: 28px;
}

/* ── Gallery ── */
.gallery {
    flex: 1; display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px; padding: 16px 20px; align-content: start;
}
.card {
    position: relative; background: #fff; border: 1px solid #d4c4a8;
    border-radius: 10px; overflow: hidden;
    transition: border-color 0.15s, transform 0.15s, box-shadow 0.15s; cursor: pointer;
}
.card:hover { border-color: #c87c2e; transform: translateY(-2px); box-shadow: 0 4px 16px #c87c2e22; }
.card.selected { border-color: #c87c2e; box-shadow: 0 0 16px #c87c2e33; }
.card .sel {
    position: absolute; top: 8px; left: 8px; z-index: 10;
    width: 20px; height: 20px; accent-color: #c87c2e; cursor: pointer;
}
.card .thumb {
    width: 100%; height: 190px; object-fit: cover;
    display: block; background: #f0e6d4;
}
.card .meta {
    padding: 7px 10px; font-size: 0.72rem;
    display: flex; justify-content: space-between; align-items: center;
}
.card .meta .dims { color: #8a7050; }
.card .meta .rating {
    padding: 1px 6px; border-radius: 3px;
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
}
.rating.explicit { background: #c83020; color: #fff; }
.rating.questionable { background: #c88a1a; color: #fff; }
.rating.safe { background: #3a7840; color: #fff; }
.card .tags {
    padding: 0 10px 7px; font-size: 0.62rem; color: #8a7050;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.empty, .loading {
    grid-column: 1 / -1; text-align: center;
    padding: 60px 20px; color: #a89060; font-size: 0.95rem;
}
.loading { color: #8a7050; }

/* ── Downloads panel ── */
.downloads-header {
    padding: 12px 20px; display: flex; gap: 10px; align-items: center;
    flex-wrap: wrap; border-bottom: 1px solid #d4c4a8;
}
.downloads-stats { display: flex; gap: 20px; font-size: 0.82rem; color: #8a7050; }
.downloads-stats span { color: #c87c2e; font-weight: 600; }
.file-list { flex: 1; overflow-y: auto; padding: 12px 20px; }
.file-item {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 12px; border-radius: 6px;
    border: 1px solid transparent; transition: all 0.1s;
}
.file-item:hover { background: #f0e6d4; border-color: #d4c4a8; }
.file-item input[type="checkbox"] { accent-color: #c87c2e; cursor: pointer; }
.file-item .fname { flex: 1; font-size: 0.85rem; color: #3a2a10; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-item .fsize { font-size: 0.75rem; color: #8a7050; white-space: nowrap; }
.file-item .fdel { color: #a89060; cursor: pointer; font-size: 0.8rem; }
.file-item .fdel:hover { color: #c83020; }

/* ── Settings panel ── */
.settings-overlay {
    display: none; position: fixed; inset: 0;
    background: #00000066; z-index: 500; align-items: center; justify-content: center;
}
.settings-overlay.open { display: flex; }
.settings-panel {
    background: #fff; border: 1px solid #d4c4a8; border-radius: 12px;
    width: 480px; max-width: 95vw; padding: 0; overflow: hidden;
    box-shadow: 0 8px 32px #00000033;
}
.settings-header {
    padding: 16px 20px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #d4c4a8;
}
.settings-header h2 { font-size: 1rem; color: #3a2a10; }
.settings-header .close-btn {
    background: none; border: none; color: #8a7050; cursor: pointer;
    font-size: 1.2rem; padding: 4px 8px;
}
.settings-header .close-btn:hover { color: #5a4030; }
.settings-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.settings-body label {
    display: block; font-size: 0.78rem; color: #8a7050; margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.settings-body input, .settings-body select {
    width: 100%; padding: 10px 12px; border: 1px solid #c8b488;
    border-radius: 8px; background: #fff; color: #2a1f10;
    font-size: 0.88rem; outline: none; transition: border-color 0.15s;
}
.settings-body input:focus, .settings-body select:focus { border-color: #c87c2e; }
.settings-body input[type="password"] { font-family: monospace; }
.settings-body .field-hint { font-size: 0.72rem; color: #8a7050; margin-top: 4px; }
.settings-body .field-hint code {
    background: #f5ede0; padding: 1px 5px; border-radius: 3px;
    color: #c87c2e; font-size: 0.75rem;
}
.settings-footer {
    padding: 14px 20px; border-top: 1px solid #d4c4a8;
    display: flex; justify-content: flex-end; gap: 10px;
}
.status-msg { padding: 6px 0; font-size: 0.8rem; min-height: 20px; }
.status-msg.ok { color: #3a7840; }
.status-msg.err { color: #c83020; }
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
    <h1>🔞</h1>
    <div class="autocomplete-wrap" style="flex:1;min-width:220px;position:relative">
        <div class="tag-area" id="tagArea" onclick="focusTagInput()">
            <!-- tag chips injected here -->
            <input type="text" id="tagInput" placeholder="Type tags..." autofocus autocomplete="off" />
        </div>
        <div class="tag-suggestions" id="tagSuggestions"></div>
    </div>
    <input type="number" id="limitInput" value="100" min="1" max="1000" title="Results per page" style="width:70px;padding:9px" />
    <button onclick="selectAllPage()">Select Page</button>
    <button onclick="deselectAll()">Deselect</button>
    <button class="primary" id="dlBtn" onclick="downloadSelected()" disabled>⬇ Download</button>
    <button class="icon-btn" onclick="openSettings()">⚙</button>
</div>

<!-- Download bar (visible when items selected) -->
<div class="download-bar hidden" id="downloadBar">
    <div class="dl-count"><strong id="dlCountNum">0</strong> selected</div>
    <div class="dl-progress-wrap">
        <div class="dl-progress-bar"><div class="dl-progress-fill" id="dlProgressFill"></div></div>
        <span class="dl-progress-text" id="dlProgressText">0%</span>
    </div>
    <button class="primary" onclick="downloadSelected()">⬇ Download</button>
    <button onclick="deselectAll()">Clear</button>
</div>

<!-- Tabs -->
<div class="tabs">
    <div class="tab active" id="tabSearch" onclick="switchTab('search')">🔍 Search</div>
    <div class="tab" id="tabDownloads" onclick="switchTab('downloads')">📁 Downloads</div>
</div>

<!-- Search panel -->
<div class="panel active" id="panelSearch">
    <div class="status-bar" id="statusBar">Type tags and press Enter or click Search.</div>
    <div class="gallery" id="gallery">
        <div class="empty"><p>Search for something to get started</p></div>
    </div>
</div>

<!-- Downloads panel -->
<div class="panel" id="panelDownloads">
    <div class="downloads-header">
        <div class="downloads-stats" id="downloadsStats">
            <span>0 files</span><span>0 MB</span>
        </div>
        <button onclick="selectAllFiles()">Select All</button>
        <button onclick="deselectAllFiles()">Deselect All</button>
        <button onclick="deleteSelectedFiles()" style="color:#c83020">Delete Selected</button>
        <button onclick="loadFiles()">↻ Refresh</button>
    </div>
    <div class="file-list" id="fileList">
        <div class="empty"><p>No downloaded files yet.</p></div>
    </div>
</div>

<!-- Settings overlay -->
<div class="settings-overlay" id="settingsOverlay">
    <div class="settings-panel">
        <div class="settings-header">
            <h2>⚙ Settings</h2>
            <button class="close-btn" onclick="closeSettings()">✕</button>
        </div>
        <div class="settings-body">
            <div>
                <label>API Credentials (rule34.xxx format)</label>
                <input type="text" id="cfgCredentials" placeholder="&api_key=...&user_id=..." />
                <div class="field-hint">Paste the full query string from your rule34 account page:<br/><code>&amp;api_key=YOUR_KEY&amp;user_id=YOUR_ID</code></div>
            </div>
            <div>
                <label>API Delay (seconds between requests)</label>
                <input type="number" id="cfgDelay" value="1.0" min="0.1" max="10" step="0.1" />
            </div>
            <div>
                <label>HTTP Timeout (seconds)</label>
                <input type="number" id="cfgTimeout" value="30" min="5" max="120" />
            </div>
            <div>
                <label>Download Directory</label>
                <input type="text" id="cfgDownloadDir" value="./downloads" />
            </div>
            <div class="status-msg" id="cfgStatus"></div>
        </div>
        <div class="settings-footer">
            <button onclick="closeSettings()">Cancel</button>
            <button class="primary" onclick="saveConfig()">Save Settings</button>
        </div>
    </div>
</div>

<script>
// ── State ──
let allPosts = [];
let selectedIds = new Set();
let selectedFileNames = new Set();
let currentTab = 'search';
let activeDlId = null;
let tagSuggestions = [];
let highlightedSuggestion = -1;

// ── Init ──
window.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadFiles();
    loadSettings();
    setupTagInput();
});

function loadStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(s => {
            document.querySelector('.topbar h1').textContent = s.configured ? '🔞' : '🔞⚠';
            document.querySelector('.topbar h1').title = s.configured
                ? `Logged in as ...${s.user_id}`
                : 'Not configured — click ⚙';
        }).catch(() => {});
}

function loadSettings() {
    fetch('/api/status').then(r => r.json()).then(s => {
        document.getElementById('cfgDelay').value = s.delay;
        document.getElementById('cfgTimeout').value = s.timeout;
        document.getElementById('cfgDownloadDir').value = s.download_dir;
        document.getElementById('cfgCredentials').placeholder = s.configured
            ? `Configured (...${s.user_id}) — enter new value to replace`
            : '&api_key=...&user_id=...';
    });
}

function loadFiles() {
    fetch('/api/files').then(r => r.json()).then(data => {
        const stats = document.getElementById('downloadsStats');
        const mb = (data.files.reduce((a, f) => a + f.size, 0) / 1024 / 1024).toFixed(1);
        stats.innerHTML = `<span>${data.total} files</span><span>${mb} MB</span>`;
        const list = document.getElementById('fileList');
        if (!data.files.length) {
            list.innerHTML = '<div class="empty"><p>No downloaded files yet.</p></div>';
            return;
        }
        list.innerHTML = data.files.map(f => `
            <div class="file-item" data-name="${esc(f.name)}">
                <input type="checkbox" onchange="toggleFile('${esc(f.name)}', this.checked)" />
                <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
                <span class="fsize">${formatSize(f.size)}</span>
                <span class="fdel" onclick="deleteFile('${esc(f.name)}')">✕</span>
            </div>`).join('');
    });
}

function esc(s) { return String(s).replace(/'/g, "\\'").replace(/"/g, '&quot;'); }
function formatSize(b) {
    if (b < 1024) return b + ' B';
    if (b < 1024 * 1024) return (b / 1024).toFixed(1) + ' KB';
    return (b / 1024 / 1024).toFixed(1) + ' MB';
}

// ── Tag Input System ──
function setupTagInput() {
    const input = document.getElementById('tagInput');
    const area = document.getElementById('tagArea');

    function syncFromTags() {
        currentTags = currentTags.filter(Boolean);
        const input2 = document.getElementById('tagInput');
        if (input2) {
            input2.value = currentTags.join(' ');
        }
        updateDlButton();
    }

    input.addEventListener('input', (e) => {
        const val = input.value.trim();
        const lastSpace = val.lastIndexOf(' ');
        const current = val.slice(lastSpace + 1);

        // Sync currentTags: treat trailing word as current input
        const parts = val.split(/\\s+/);
        currentTags = parts.slice(0, -1).filter(Boolean);
        const incomplete = parts[parts.length - 1] || '';

        // Render chips for completed tags
        let chipsHtml = currentTags.map(t => `
            <div class="tag-chip">
                <span>${esc(t)}</span>
                <span class="remove-tag" onclick="event.stopPropagation(); currentTags=currentTags.filter(x=>x!=='${esc(t)}'); renderChips();">X</span>
            </div>`).join('');

        // Put the chip area + input back
        area.innerHTML = chipsHtml + `<input type="text" id="tagInput" placeholder="" autofocus autocomplete="off" />`;
        const newInput = document.getElementById('tagInput');
        newInput.value = incomplete;
        newInput.focus();
        updateDlButton();

        if (incomplete.length >= 2) {
            fetchSuggestions(incomplete);
        } else {
            closeSuggestions();
        }
    });

    input.addEventListener('keydown', (e) => {
        const newInput = document.getElementById('tagInput');
        const val = newInput.value.trim();

        if (e.key === ' ') {
            e.preventDefault();
            if (val) {
                addTag(val);
                newInput.value = '';
                renderChips();
            }
            closeSuggestions();
        } else if (e.key === 'Enter') {
            e.preventDefault();
            if (val) addTag(val);
            newInput.value = '';
            renderChips();
            closeSuggestions();
            if (currentTags.length > 0) search();
        } else if (e.key === 'Backspace' && val === '' && currentTags.length > 0) {
            currentTags.pop();
            renderChips();
        } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            if (tagSuggestions.length) {
                highlightedSuggestion = Math.min(highlightedSuggestion + 1, tagSuggestions.length - 1);
                renderSuggestions();
            }
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            if (tagSuggestions.length) {
                highlightedSuggestion = Math.max(highlightedSuggestion - 1, 0);
                renderSuggestions();
            }
        } else if (e.key === 'Escape') {
            closeSuggestions();
        }
    });
}

function renderChips() {
    const area = document.getElementById('tagArea');
    let html = currentTags.map(t => `
        <div class="tag-chip">
            <span>${esc(t)}</span>
            <span class="remove-tag" onclick="event.stopPropagation(); currentTags=currentTags.filter(x=>x!=='${esc(t)}'); renderChips();">X</span>
        </div>`).join('');
    html += `<input type="text" id="tagInput" placeholder="" autofocus autocomplete="off" />`;
    area.innerHTML = html;
    const input = document.getElementById('tagInput');
    input.focus();
    setupTagInput();
    updateDlButton();
}

function addTag(tag) {
    tag = tag.trim().replace(/\\s+/g, '_');
    if (tag && !currentTags.includes(tag)) {
        currentTags.push(tag);
    }
}

function fetchSuggestions(prefix) {
    clearTimeout(window._suggestDebounce);
    window._suggestDebounce = setTimeout(() => {
        fetch('/api/tags?q=' + encodeURIComponent(prefix))
            .then(r => r.json())
            .then(tags => {
                tagSuggestions = tags.filter(t => !currentTags.includes(t));
                highlightedSuggestion = -1;
                renderSuggestions();
            }).catch(() => { tagSuggestions = []; });
    }, 200);
}

function renderSuggestions() {
    const el = document.getElementById('tagSuggestions');
    if (!tagSuggestions.length) { el.classList.remove('open'); return; }
    el.classList.add('open');
    el.innerHTML = tagSuggestions.map((t, i) =>
        `<div class="tag-suggestion${i === highlightedSuggestion ? ' highlighted' : ''}" onclick="pickSuggestion(${i})">${esc(t)}</div>`
    ).join('');
}

function pickSuggestion(i) {
    const tag = tagSuggestions[i];
    if (tag) {
        addTag(tag);
        renderChips();
        closeSuggestions();
        // Focus back on input
        setTimeout(() => {
            const input = document.getElementById('tagInput');
            if (input) { input.focus(); }
        }, 10);
    }
}

function closeSuggestions() {
    document.getElementById('tagSuggestions').classList.remove('open');
    tagSuggestions = [];
    highlightedSuggestion = -1;
}

function focusTagInput() {
    const input = document.getElementById('tagInput');
    if (input) input.focus();
}

// ── Tabs ──
function switchTab(tab) {
    currentTab = tab;
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.getElementById('tab' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById('panel' + tab.charAt(0).toUpperCase() + tab.slice(1)).classList.add('active');
    if (tab === 'downloads') loadFiles();
}

// ── Search ──
function search() {
    const tags = getCurrentTags();
    if (!tags.length) return;
    const limit = document.getElementById('limitInput')?.value || 100;

    document.getElementById('statusBar').textContent = 'Searching...';
    document.getElementById('gallery').innerHTML = '<div class="loading">Searching...</div>';

    fetch(`/api/search?tags=${encodeURIComponent(tags.join(' '))}&limit=${limit}`)
        .then(r => r.json())
        .then(posts => {
            if (posts.error) throw new Error(posts.error);
            allPosts = posts;
            selectedIds.clear();
            renderGallery();
            const msg = posts.length === 0 ? 'No results' : `${posts.length} results`;
            document.getElementById('statusBar').textContent = `${msg} for "${tags.join(' ')}"`;
        })
        .catch(e => {
            document.getElementById('gallery').innerHTML = `<div class="empty"><p>Error: ${e.message}</p></div>`;
            document.getElementById('statusBar').textContent = 'Search failed.';
        });
}

function renderGallery() {
    const gallery = document.getElementById('gallery');
    if (!allPosts.length) {
        gallery.innerHTML = '<div class="empty"><p>No results found</p></div>';
        return;
    }
    gallery.innerHTML = allPosts.map(p => `
        <div class="card${selectedIds.has(p.id) ? ' selected' : ''}" data-id="${p.id}" onclick="toggleCard(${p.id}, event)">
            <input type="checkbox" class="sel" ${selectedIds.has(p.id) ? 'checked' : ''} onclick="event.stopPropagation(); toggleCard(${p.id}, event)" />
            <img class="thumb" src="${p.preview_url}" alt="Post ${p.id}" loading="lazy"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 200%22><rect fill=%22%23f0e6d4%22 width=%22200%22 height=%22200%22/><text fill=%22%23c8b488%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dy=%22.3em%22>Err</text></svg>'" />
            <div class="meta">
                <span class="dims">${p.width}×${p.height}</span>
                <span class="rating ${p.rating}">${p.rating || '?'}</span>
            </div>
            <div class="tags">${(p.tags || []).slice(0, 5).join(' ')}</div>
        </div>`).join('');
    updateDlButton();
}

function toggleCard(id, event) {
    if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    const card = document.querySelector(`.card[data-id="${id}"]`);
    if (card) card.classList.toggle('selected', selectedIds.has(id));
    const cb = card?.querySelector('.sel');
    if (cb) cb.checked = selectedIds.has(id);
    updateDlButton();
}

function selectAllPage() {
    allPosts.forEach(p => selectedIds.add(p.id));
    renderGallery();
}

function deselectAll() {
    selectedIds.clear();
    renderGallery();
}

function updateDlButton() {
    const dlBtn = document.getElementById('dlBtn');
    const dlBar = document.getElementById('downloadBar');
    const dlCountNum = document.getElementById('dlCountNum');
    const hasSel = selectedIds.size > 0;
    if (dlBtn) {
        dlBtn.disabled = !hasSel;
        dlBtn.textContent = hasSel ? `⬇ Download (${selectedIds.size})` : '⬇ Download';
    }
    if (dlBar) dlBar.classList.toggle('hidden', !hasSel);
    if (dlCountNum) dlCountNum.textContent = selectedIds.size;
}

// ── Download ──
function downloadSelected() {
    if (selectedIds.size === 0) { alert('Select at least one image first.'); return; }

    const fill = document.getElementById('dlProgressFill');
    const text = document.getElementById('dlProgressText');
    if (fill) { fill.style.width = '0%'; }
    if (text) { text.textContent = '0%'; }

    fetch('/api/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: Array.from(selectedIds)})
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) throw new Error(data.error);
        pollProgress(data.download_id);
    })
    .catch(e => {
        if (text) text.textContent = 'Error: ' + e.message;
    });
}

function pollProgress(dlId) {
    activeDlId = dlId;
    const fill = document.getElementById('dlProgressFill');
    const text = document.getElementById('dlProgressText');

    const interval = setInterval(() => {
        fetch('/api/download/' + dlId)
            .then(r => r.json())
            .then(prog => {
                const pct = prog.total > 0 ? Math.round((prog.done / prog.total) * 100) : 0;
                if (fill) fill.style.width = pct + '%';
                if (text) text.textContent = `${prog.done}/${prog.total}`;
                if (prog.status === 'complete') {
                    clearInterval(interval);
                    const failInfo = prog.failed > 0 ? `, ${prog.failed} fail` : '';
                    if (text) {
                        text.textContent = `✓ Done (${prog.skipped} skip${failInfo})`;
                        text.style.color = prog.failed > 0 ? '#c88a1a' : '#3a7840';
                    }
                    setTimeout(() => {
                        if (fill) { fill.style.width = '0%'; }
                        if (text) { text.textContent = '0%'; text.style.color = ''; }
                        selectedIds.clear();
                        renderGallery();
                    }, 3500);
                }
            });
    }, 800);
}

// ── Files ──
function toggleFile(name, checked) {
    if (checked) selectedFileNames.add(name);
    else selectedFileNames.delete(name);
}

function selectAllFiles() {
    document.querySelectorAll('#fileList input[type="checkbox"]').forEach(cb => {
        cb.checked = true;
        const n = cb.closest('.file-item')?.dataset.name;
        if (n) selectedFileNames.add(n);
    });
}

function deselectAllFiles() {
    document.querySelectorAll('#fileList input[type="checkbox"]').forEach(cb => cb.checked = false);
    selectedFileNames.clear();
}

function deleteFile(name) {
    if (!confirm('Delete ' + name + '?')) return;
    fetch('/api/files/' + encodeURIComponent(name), {method: 'DELETE'})
        .then(r => r.json())
        .then(() => loadFiles())
        .catch(e => alert('Delete failed: ' + e.message));
}

function deleteSelectedFiles() {
    if (!selectedFileNames.size) { alert('Select files first.'); return; }
    if (!confirm('Delete ' + selectedFileNames.size + ' files?')) return;
    fetch('/api/files/delete_batch', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({names: Array.from(selectedFileNames)})
    })
    .then(r => r.json())
    .then(() => { selectedFileNames.clear(); loadFiles(); })
    .catch(e => alert('Delete failed: ' + e.message));
}

// ── Settings ──
function openSettings() {
    document.getElementById('settingsOverlay').classList.add('open');
    loadSettings();
}

function closeSettings() {
    document.getElementById('settingsOverlay').classList.remove('open');
    document.getElementById('cfgStatus').textContent = '';
    document.getElementById('cfgStatus').className = 'status-msg';
}

function saveConfig() {
    const credentials = document.getElementById('cfgCredentials').value.trim();
    const delay = parseFloat(document.getElementById('cfgDelay').value);
    const timeout = parseInt(document.getElementById('cfgTimeout').value);
    const download_dir = document.getElementById('cfgDownloadDir').value.trim();
    const statusEl = document.getElementById('cfgStatus');

    const body = {};
    if (credentials) body.credentials = credentials;
    if (!isNaN(delay)) body.delay = delay;
    if (!isNaN(timeout)) body.timeout = timeout;
    if (download_dir) body.download_dir = download_dir;

    fetch('/api/config', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(body)
    })
    .then(r => r.json())
    .then(data => {
        if (data.configured) {
            statusEl.textContent = '✓ Settings saved. API connected.';
            statusEl.className = 'status-msg ok';
            loadStatus();
            setTimeout(closeSettings, 1500);
        } else {
            statusEl.textContent = '⚠ Saved but API not configured — check credentials.';
            statusEl.className = 'status-msg err';
        }
    })
    .catch(e => {
        statusEl.textContent = 'Error: ' + e.message;
        statusEl.className = 'status-msg err';
    });
}
</script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


# ─── Startup ────────────────────────────────────────────────────

if __name__ == "__main__":
    print("╔══════════════════════════════════════╗")
    print("║       Rule34 Tool — Web UI          ║")
    print("╠══════════════════════════════════════╣")
    load_config()
    print(f"║  Downloads → {download_dir}       ")
    print(f"║  Open      → http://localhost:8010  ║")
    if not (cfg and cfg.has_credentials):
        print("║  ⚠ API not configured — click ⚙   ║")
    print("╚══════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=8010, debug=False)