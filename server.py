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
    background: #100d0a; color: #e0cfa8;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    min-height: 100vh; display: flex; flex-direction: column;
}
/* ── Topbar ── */
.topbar {
    position: sticky; top: 0; z-index: 100;
    background: #100d0aee; backdrop-filter: blur(12px);
    border-bottom: 1px solid #2a2018;
    padding: 14px 20px;
    display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
}
.topbar h1 { font-size: 1rem; color: #e0cfa8; margin-right: 8px; white-space: nowrap; }
.topbar input[type="text"] {
    flex: 1; min-width: 180px;
    padding: 9px 13px; border: 1px solid #3a2e1e; border-radius: 8px;
    background: #1a1510; color: #e0cfa8; font-size: 0.9rem; outline: none;
    transition: border-color 0.15s;
}
.topbar input[type="text"]:focus { border-color: #c87c2e; }
.topbar input[type="number"] { width: 75px; }
.topbar button {
    padding: 9px 18px; border: 1px solid #3a2e1e; border-radius: 8px;
    background: #1a1510; color: #c8b488; cursor: pointer;
    font-size: 0.88rem; transition: all 0.15s; white-space: nowrap;
}
.topbar button:hover { background: #201a12; border-color: #5a4830; }
.topbar button.primary { background: #c87c2e; border-color: #c87c2e; color: #100d0a; }
.topbar button.primary:hover { background: #a86820; }
.topbar button.icon-btn { padding: 9px 14px; font-size: 1rem; }
.topbar button.active { background: #c87c2e; border-color: #c87c2e; color: #100d0a; }

/* ── Tabs ── */
.tabs {
    display: flex; padding: 0 20px; gap: 0;
    background: #100d0a; border-bottom: 1px solid #1a150e;
}
.tab {
    padding: 10px 20px; cursor: pointer; font-size: 0.88rem;
    color: #6a5840; border-bottom: 2px solid transparent;
    transition: all 0.15s;
}
.tab:hover { color: #c8b488; }
.tab.active { color: #c87c2e; border-bottom-color: #c87c2e; }

/* ── Panels ── */
.panel { display: none; flex: 1; }
.panel.active { display: flex; flex-direction: column; }

/* ── Status bar ── */
.status-bar {
    padding: 8px 20px; font-size: 0.78rem; color: #5a4838;
    border-bottom: 1px solid #1a150e; min-height: 28px;
}

/* ── Search panel ── */
.search-controls {
    padding: 12px 20px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap;
    border-bottom: 1px solid #1a150e;
}
.search-controls label { font-size: 0.78rem; color: #5a4838; white-space: nowrap; }
.search-controls input { vertical-align: middle; }

/* ── Gallery ── */
.gallery {
    flex: 1; display: grid;
    grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
    gap: 12px; padding: 16px 20px; align-content: start;
}
.card {
    position: relative; background: #1a1510; border: 1px solid #2a2018;
    border-radius: 10px; overflow: hidden;
    transition: border-color 0.15s, transform 0.15s; cursor: pointer;
}
.card:hover { border-color: #4a3828; transform: translateY(-2px); }
.card.selected { border-color: #c87c2e; box-shadow: 0 0 16px #c87c2e22; }
.card .sel {
    position: absolute; top: 8px; left: 8px; z-index: 10;
    width: 20px; height: 20px; accent-color: #c87c2e; cursor: pointer;
}
.card .thumb {
    width: 100%; height: 190px; object-fit: cover;
    display: block; background: #141008;
}
.card .meta {
    padding: 7px 10px; font-size: 0.72rem;
    display: flex; justify-content: space-between; align-items: center;
}
.card .meta .dims { color: #6a5840; }
.card .meta .rating {
    padding: 1px 6px; border-radius: 3px;
    font-size: 0.62rem; font-weight: 700; text-transform: uppercase;
}
.rating.explicit { background: #a83820; color: #fff; }
.rating.questionable { background: #c88a1a; color: #100d0a; }
.rating.safe { background: #3a7840; color: #fff; }
.card .tags {
    padding: 0 10px 7px; font-size: 0.62rem; color: #5a4838;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.empty, .loading {
    grid-column: 1 / -1; text-align: center;
    padding: 60px 20px; color: #3a2e1e; font-size: 0.95rem;
}
.loading { color: #6a5840; }

/* ── Downloads panel ── */
.downloads-header {
    padding: 12px 20px; display: flex; gap: 10px; align-items: center;
    flex-wrap: wrap; border-bottom: 1px solid #1a150e;
}
.downloads-stats {
    display: flex; gap: 20px; font-size: 0.82rem; color: #6a5840;
}
.downloads-stats span { color: #c87c2e; }
.file-list { flex: 1; overflow-y: auto; padding: 12px 20px; }
.file-item {
    display: flex; align-items: center; gap: 12px;
    padding: 8px 12px; border-radius: 6px;
    border: 1px solid transparent; transition: all 0.1s;
}
.file-item:hover { background: #1a1510; border-color: #2a2018; }
.file-item input[type="checkbox"] { accent-color: #c87c2e; cursor: pointer; }
.file-item .fname { flex: 1; font-size: 0.85rem; color: #c8b488; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.file-item .fsize { font-size: 0.75rem; color: #6a5840; white-space: nowrap; }
.file-item .fdel { color: #5a4838; cursor: pointer; font-size: 0.8rem; }
.file-item .fdel:hover { color: #a83820; }

/* ── Bottom bar ── */
.bottom-bar {
    position: fixed; bottom: 0; left: 0; right: 0;
    background: #100d0aee; backdrop-filter: blur(12px);
    border-top: 1px solid #2a2018;
    padding: 12px 20px;
    display: flex; align-items: center; justify-content: space-between;
    z-index: 200; gap: 16px;
}
.bottom-bar.hidden { display: none; }
.bottom-bar .selected-count { color: #c87c2e; font-weight: 600; font-size: 0.9rem; }
.bottom-bar .actions { display: flex; gap: 10px; align-items: center; }
.progress-bar {
    flex: 1; height: 5px; background: #2a2018; border-radius: 3px;
    overflow: hidden; max-width: 280px; display: none;
}
.progress-bar .fill {
    height: 100%; background: #c87c2e; border-radius: 3px;
    transition: width 0.3s; width: 0%;
}

/* ── Settings panel ── */
.settings-overlay {
    display: none; position: fixed; inset: 0;
    background: #000000aa; z-index: 500; align-items: center; justify-content: center;
}
.settings-overlay.open { display: flex; }
.settings-panel {
    background: #1a1510; border: 1px solid #3a2e1e; border-radius: 12px;
    width: 480px; max-width: 95vw; padding: 0; overflow: hidden;
}
.settings-header {
    padding: 16px 20px; display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid #2a2018;
}
.settings-header h2 { font-size: 1rem; color: #e0cfa8; }
.settings-header .close-btn {
    background: none; border: none; color: #6a5840; cursor: pointer;
    font-size: 1.2rem; padding: 4px 8px;
}
.settings-header .close-btn:hover { color: #c8b488; }
.settings-body { padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.settings-body label {
    display: block; font-size: 0.78rem; color: #6a5840; margin-bottom: 6px;
    text-transform: uppercase; letter-spacing: 0.05em;
}
.settings-body input, .settings-body select {
    width: 100%; padding: 10px 12px; border: 1px solid #3a2e1e;
    border-radius: 8px; background: #141008; color: #e0cfa8;
    font-size: 0.88rem; outline: none; transition: border-color 0.15s;
}
.settings-body input:focus, .settings-body select:focus { border-color: #c87c2e; }
.settings-body input[type="password"] { font-family: monospace; }
.settings-body .field-hint { font-size: 0.72rem; color: #5a4838; margin-top: 4px; }
.settings-body .field-hint code {
    background: #201a12; padding: 1px 5px; border-radius: 3px;
    color: #c87c2e; font-size: 0.75rem;
}
.settings-footer {
    padding: 14px 20px; border-top: 1px solid #2a2018;
    display: flex; justify-content: flex-end; gap: 10px;
}
.status-msg {
    padding: 6px 0; font-size: 0.8rem; min-height: 20px;
}
.status-msg.ok { color: #5a9a60; }
.status-msg.err { color: #a83820; }
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
    <h1>🔞</h1>
    <input type="text" id="tagInput" placeholder="Enter tags (space-separated)..." autofocus
           onkeydown="if(event.key==='Enter')search()" style="max-width:500px" />
    <button class="primary" onclick="search()">Search</button>
    <input type="number" id="limitInput" value="100" min="1" max="1000" title="Max results per page" style="width:70px" />
    <button onclick="selectAll()">All</button>
    <button onclick="deselectAll()">None</button>
    <button class="primary" id="dlBtn" onclick="downloadSelected()">⬇</button>
    <button class="icon-btn" onclick="openSettings()">⚙</button>
</div>

<!-- Tabs -->
<div class="tabs">
    <div class="tab active" id="tabSearch" onclick="switchTab('search')">🔍 Search</div>
    <div class="tab" id="tabDownloads" onclick="switchTab('downloads')">📁 Downloads</div>
</div>

<!-- Search panel -->
<div class="panel active" id="panelSearch">
    <div class="status-bar" id="statusBar">Enter tags and click Search to begin.</div>
    <div class="gallery" id="gallery">
        <div class="empty"><p>Search for something to get started</p></div>
    </div>
</div>

<!-- Downloads panel -->
<div class="panel" id="panelDownloads">
    <div class="downloads-header">
        <div class="downloads-stats" id="downloadsStats">
            <span>0 files</span>
            <span>0 MB</span>
        </div>
        <button onclick="selectAllFiles()">Select All</button>
        <button onclick="deselectAllFiles()">Deselect All</button>
        <button onclick="deleteSelectedFiles()" style="color:#dc2626">Delete Selected</button>
        <button onclick="loadFiles()">↻ Refresh</button>
    </div>
    <div class="file-list" id="fileList">
        <div class="empty"><p>No downloaded files yet. Search and download images to see them here.</p></div>
    </div>
</div>

<!-- Bottom bar -->
<div class="bottom-bar hidden" id="bottomBar">
    <span><span class="selected-count" id="selectedCount">0</span> selected</span>
    <div class="actions">
        <span id="dlStatus" style="font-size:0.8rem;color:#555"></span>
        <div class="progress-bar" id="progressBar"><div class="fill" id="progressFill"></div></div>
        <button onclick="downloadSelected()">⬇ Download Selected</button>
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
                <div class="field-hint">
                    Paste the full query string from your rule34 account page:<br/>
                    <code>&amp;api_key=YOUR_KEY&amp;user_id=YOUR_ID</code>
                </div>
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
let currentDlId = null;

// ── Init ──
window.addEventListener('DOMContentLoaded', () => {
    loadStatus();
    loadFiles();
    loadSettings();
});

function loadStatus() {
    fetch('/api/status')
        .then(r => r.json())
        .then(s => {
            const badge = document.querySelector('.topbar h1');
            badge.textContent = s.configured ? '🔞' : '🔞⚠';
            badge.title = s.configured
                ? `Logged in as ...${s.user_id}`
                : 'Not configured — click ⚙ to add credentials';
        })
        .catch(() => {});
}

function loadSettings() {
    fetch('/api/status')
        .then(r => r.json())
        .then(s => {
            document.getElementById('cfgDelay').value = s.delay;
            document.getElementById('cfgTimeout').value = s.timeout;
            document.getElementById('cfgDownloadDir').value = s.download_dir;
        });
}

function loadFiles() {
    fetch('/api/files')
        .then(r => r.json())
        .then(data => {
            const stats = document.getElementById('downloadsStats');
            const mb = (data.files.reduce((a, f) => a + f.size, 0) / 1024 / 1024).toFixed(1);
            stats.innerHTML = `<span>${data.total} files</span><span>${mb} MB</span>`;

            const list = document.getElementById('fileList');
            if (data.files.length === 0) {
                list.innerHTML = '<div class="empty"><p>No downloaded files yet.</p></div>';
                return;
            }
            list.innerHTML = data.files.map(f => `
                <div class="file-item" data-name="${esc(f.name)}">
                    <input type="checkbox" onchange="toggleFile('${esc(f.name)}', this.checked)" />
                    <span class="fname" title="${esc(f.name)}">${esc(f.name)}</span>
                    <span class="fsize">${formatSize(f.size)}</span>
                    <span class="fdel" onclick="deleteFile('${esc(f.name)}')">✕</span>
                </div>
            `).join('');
        });
}

function esc(s) { return String(s).replace(/'/g, "\\'").replace(/"/g, '&quot;'); }
function formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / 1024 / 1024).toFixed(1) + ' MB';
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
    const tags = document.getElementById('tagInput').value.trim();
    if (!tags) return;
    const limit = document.getElementById('limitInput').value || 100;

    document.getElementById('statusBar').textContent = 'Searching...';
    document.getElementById('gallery').innerHTML = '<div class="loading">Searching...</div>';

    fetch(`/api/search?tags=${encodeURIComponent(tags)}&limit=${limit}`)
        .then(r => r.json())
        .then(posts => {
            if (posts.error) throw new Error(posts.error);
            allPosts = posts;
            selectedIds.clear();
            renderGallery();
            const msg = posts.length === 0 ? 'No results' : `${posts.length} results`;
            document.getElementById('statusBar').textContent = `${msg} for "${tags}"`;
        })
        .catch(e => {
            document.getElementById('gallery').innerHTML =
                `<div class="empty"><p>Error: ${e.message}</p></div>`;
            document.getElementById('statusBar').textContent = 'Search failed.';
        });
}

function renderGallery() {
    const gallery = document.getElementById('gallery');
    if (allPosts.length === 0) {
        gallery.innerHTML = '<div class="empty"><p>No results found</p></div>';
        return;
    }
    gallery.innerHTML = allPosts.map(p => `
        <div class="card${selectedIds.has(p.id) ? ' selected' : ''}" data-id="${p.id}"
             onclick="toggleCard(${p.id}, event)">
            <input type="checkbox" class="sel" ${selectedIds.has(p.id) ? 'checked' : ''}
                   onclick="event.stopPropagation(); toggleCard(${p.id}, event)" />
            <img class="thumb" src="${p.preview_url}" alt="Post ${p.id}" loading="lazy"
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 200%22><rect fill=%22%23111%22 width=%22200%22 height=%22200%22/><text fill=%22%23333%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dy=%22.3em%22>Err</text></svg>'" />
            <div class="meta">
                <span class="dims">${p.width}×${p.height}</span>
                <span class="rating ${p.rating}">${p.rating || '?'}</span>
            </div>
            <div class="tags">${(p.tags || []).slice(0, 5).join(' ')}</div>
        </div>
    `).join('');
    updateBottomBar();
}

function toggleCard(id, event) {
    if (selectedIds.has(id)) selectedIds.delete(id);
    else selectedIds.add(id);
    const card = document.querySelector(`.card[data-id="${id}"]`);
    if (card) card.classList.toggle('selected', selectedIds.has(id));
    const cb = card?.querySelector('.sel');
    if (cb) cb.checked = selectedIds.has(id);
    updateBottomBar();
}

function selectAll() { allPosts.forEach(p => selectedIds.add(p.id)); renderGallery(); }
function deselectAll() { selectedIds.clear(); renderGallery(); }

function updateBottomBar() {
    const bar = document.getElementById('bottomBar');
    document.getElementById('selectedCount').textContent = selectedIds.size;
    bar.classList.toggle('hidden', selectedIds.size === 0);
}

// ── Download ──
function downloadSelected() {
    if (selectedIds.size === 0) { alert('Select at least one image first.'); return; }

    const bar = document.getElementById('progressBar');
    const fill = document.getElementById('progressFill');
    const status = document.getElementById('dlStatus');
    bar.style.display = 'block';
    fill.style.width = '0%';
    status.textContent = 'Starting...';

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
    .catch(e => { status.textContent = 'Error: ' + e.message; });
}

function pollProgress(dlId) {
    currentDlId = dlId;
    const fill = document.getElementById('progressFill');
    const status = document.getElementById('dlStatus');
    const bar = document.getElementById('progressBar');

    const interval = setInterval(() => {
        fetch('/api/download/' + dlId)
            .then(r => r.json())
            .then(prog => {
                const pct = prog.total > 0 ? Math.round((prog.done / prog.total) * 100) : 0;
                fill.style.width = pct + '%';
                status.textContent = `${prog.done}/${prog.total} done`;
                if (prog.status === 'complete') {
                    clearInterval(interval);
                    const failInfo = prog.failed > 0 ? `, ${prog.failed} failed` : '';
                    status.textContent = `✓ Done (${prog.skipped} skipped${failInfo})`;
                    status.style.color = prog.failed > 0 ? '#f59e0b' : '#16a34a';
                    setTimeout(() => {
                        bar.style.display = 'none';
                        status.textContent = '';
                        status.style.color = '';
                        selectedIds.clear();
                        renderGallery();
                    }, 3000);
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
        const name = cb.closest('.file-item').dataset.name;
        if (name) selectedFileNames.add(name);
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
    if (selectedFileNames.size === 0) { alert('Select files first.'); return; }
    if (!confirm('Delete ' + selectedFileNames.size + ' files?')) return;
    fetch('/api/files/delete_batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
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
    fetch('/api/status').then(r => r.json()).then(s => {
        document.getElementById('cfgCredentials').value = '';
        document.getElementById('cfgCredentials').placeholder = s.configured
            ? `Configured (user_id ends in ...${s.user_id}) — enter new value to replace`
            : '&api_key=...&user_id=...';
    });
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
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
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