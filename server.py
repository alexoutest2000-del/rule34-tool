#!/usr/bin/env python3
"""rule34-tool — Local web interface for searching and downloading from rule34.xxx.

Run:   python server.py
Then:  http://localhost:8080
"""

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
download_progress: dict = {}  # {download_id: {"total": N, "done": N, "failed": N, "status": "..."}}


def init():
    global api, cfg, download_dir
    cfg = Config.load()
    if not cfg.user_id or not cfg.api_key:
        raise RuntimeError(
            "API credentials not configured. Create ~/.config/rule34-tool/config.yaml "
            "with user_id and api_key fields."
        )
    api = Rule34API(
        user_id=cfg.user_id,
        api_key=cfg.api_key,
        delay=cfg.delay,
        timeout=cfg.timeout,
    )
    download_dir = Path(cfg.download_dir).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)


# ─── API Endpoints ──────────────────────────────────────────────

@app.route("/api/search")
def api_search():
    """Search posts by tags."""
    tags = request.args.get("tags", "").strip()
    limit = request.args.get("limit", 50, type=int)
    page = request.args.get("page", 0, type=int)

    if not tags:
        return jsonify({"error": "No tags provided"}), 400

    tag_list = tags.split()
    try:
        posts = api.search(tag_list, limit=min(limit, 1000), page=page)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify([
        {
            "id": p.id,
            "tags": p.tag_list,
            "preview_url": p.preview_url,
            "sample_url": p.sample_url,
            "file_url": p.file_url,
            "width": p.width,
            "height": p.height,
            "rating": p.rating,
            "score": p.score,
            "filename": p.filename,
            "ext": p.ext,
        }
        for p in posts
    ])


@app.route("/api/search_all")
def api_search_all():
    """Paginate through all results up to max_results."""
    tags = request.args.get("tags", "").strip()
    max_results = request.args.get("max", 200, type=int)

    if not tags:
        return jsonify({"error": "No tags provided"}), 400

    tag_list = tags.split()
    try:
        posts = api.search_all(tag_list, max_results=min(max_results, 5000))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify([
        {
            "id": p.id,
            "tags": p.tag_list,
            "preview_url": p.preview_url,
            "sample_url": p.sample_url,
            "file_url": p.file_url,
            "width": p.width,
            "height": p.height,
            "rating": p.rating,
            "score": p.score,
            "filename": p.filename,
            "ext": p.ext,
        }
        for p in posts
    ])


@app.route("/api/download", methods=["POST"])
def api_download():
    """Download specific posts by ID. Returns progress tracking."""
    data = request.get_json(force=True)
    ids = data.get("ids", [])
    mode = data.get("mode", "download")  # "download" or "zip"

    if not ids:
        return jsonify({"error": "No IDs provided"}), 400

    download_id = f"dl_{int(time.time())}"
    download_progress[download_id] = {
        "total": len(ids),
        "done": 0,
        "failed": 0,
        "skipped": 0,
        "status": "starting",
        "files": [],
    }

    def do_download():
        import requests as req
        for pid in ids:
            try:
                post = api.get_post(pid)
                if not post:
                    download_progress[download_id]["failed"] += 1
                    continue

                dest = download_dir / post.filename
                if dest.exists():
                    download_progress[download_id]["skipped"] += 1
                else:
                    resp = req.get(post.file_url, timeout=60, stream=True)
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
    """Poll download progress."""
    prog = download_progress.get(download_id)
    if not prog:
        return jsonify({"error": "Unknown download"}), 404
    return jsonify(prog)


@app.route("/api/download/<download_id>/zip")
def api_download_zip(download_id):
    """Serve completed download as ZIP."""
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
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"rule34_download_{download_id}.zip",
    )


# ─── UI ─────────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rule34 Tool</title>
<style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        background: #0a0a0a;
        color: #ccc;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        min-height: 100vh;
        display: flex; flex-direction: column;
    }
    .topbar {
        position: sticky; top: 0; z-index: 100;
        background: #0a0a0aee; backdrop-filter: blur(12px);
        border-bottom: 1px solid #1a1a1a;
        padding: 16px 24px;
        display: flex; gap: 12px; align-items: center;
        flex-wrap: wrap;
    }
    .topbar h1 {
        font-size: 1.1rem; color: #eee; margin-right: 16px;
        white-space: nowrap;
    }
    .topbar input[type="text"] {
        flex: 1; min-width: 200px;
        padding: 10px 14px; border: 1px solid #2a2a2a; border-radius: 8px;
        background: #111; color: #eee; font-size: 0.9rem;
        outline: none; transition: border-color 0.15s;
    }
    .topbar input[type="text"]:focus { border-color: #7c3aed; }
    .topbar button {
        padding: 10px 20px; border: 1px solid #2a2a2a; border-radius: 8px;
        background: #111; color: #ccc; cursor: pointer;
        font-size: 0.9rem; transition: all 0.15s; white-space: nowrap;
    }
    .topbar button:hover { background: #1a1a1a; border-color: #444; }
    .topbar button.primary { background: #7c3aed; border-color: #7c3aed; color: #fff; }
    .topbar button.primary:hover { background: #6d28d9; }
    .topbar .limit { width: 80px; }
    .status-bar {
        padding: 8px 24px; font-size: 0.8rem; color: #555;
        border-bottom: 1px solid #111;
    }
    .gallery {
        flex: 1;
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
        gap: 12px;
        padding: 20px;
        align-content: start;
    }
    .card {
        position: relative;
        background: #111;
        border: 1px solid #1a1a1a;
        border-radius: 10px;
        overflow: hidden;
        transition: border-color 0.15s, transform 0.15s;
        cursor: pointer;
    }
    .card:hover { border-color: #333; transform: translateY(-2px); }
    .card.selected { border-color: #7c3aed; box-shadow: 0 0 16px #7c3aed22; }
    .card .sel {
        position: absolute; top: 8px; left: 8px; z-index: 10;
        width: 22px; height: 22px; accent-color: #7c3aed;
        cursor: pointer;
    }
    .card .thumb {
        width: 100%; height: 200px; object-fit: cover;
        display: block; background: #0d0d0d;
    }
    .card .meta {
        padding: 8px 10px; font-size: 0.75rem;
        display: flex; justify-content: space-between; align-items: center;
    }
    .card .meta .dims { color: #555; }
    .card .meta .rating {
        padding: 1px 6px; border-radius: 3px;
        font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
    }
    .rating.explicit { background: #dc2626; color: #fff; }
    .rating.questionable { background: #f59e0b; color: #000; }
    .rating.safe { background: #16a34a; color: #fff; }
    .card .tags {
        padding: 0 10px 8px; font-size: 0.65rem; color: #444;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }
    .bottom-bar {
        position: fixed; bottom: 0; left: 0; right: 0;
        background: #0a0a0aee; backdrop-filter: blur(12px);
        border-top: 1px solid #1a1a1a;
        padding: 14px 24px;
        display: flex; align-items: center; justify-content: space-between;
        z-index: 200;
        gap: 16px;
    }
    .bottom-bar.hidden { display: none; }
    .bottom-bar .selected-count { color: #a78bfa; font-weight: 600; }
    .bottom-bar .actions { display: flex; gap: 10px; }
    .progress-bar {
        flex: 1; height: 6px; background: #1a1a1a; border-radius: 3px;
        overflow: hidden; max-width: 300px;
    }
    .progress-bar .fill {
        height: 100%; background: #7c3aed; border-radius: 3px;
        transition: width 0.3s; width: 0%;
    }
    .empty {
        grid-column: 1 / -1;
        text-align: center; padding: 60px 20px; color: #333;
        font-size: 1rem;
    }
    .empty p { margin: 8px 0; }
    .loading {
        grid-column: 1 / -1;
        text-align: center; padding: 60px 20px; color: #555;
    }
</style>
</head>
<body>
<div class="topbar">
    <h1>🔞 Rule34 Tool</h1>
    <input type="text" id="tagInput" placeholder="Enter tags (space-separated)..." autofocus
           onkeydown="if(event.key==='Enter')search()" />
    <button class="primary" onclick="search()">Search</button>
    <input type="number" class="limit" id="limitInput" value="100" min="1" max="1000" title="Max results" />
    <button onclick="selectAll()">Select All</button>
    <button onclick="deselectAll()">Deselect All</button>
    <button class="primary" id="dlBtn" onclick="downloadSelected()">⬇ Download Selected</button>
</div>
<div class="status-bar" id="statusBar">Enter tags and click Search to begin.</div>
<div class="gallery" id="gallery">
    <div class="empty"><p>Search for something to get started</p></div>
</div>
<div class="bottom-bar hidden" id="bottomBar">
    <span><span class="selected-count" id="selectedCount">0</span> selected</span>
    <div class="actions">
        <span id="dlStatus"></span>
        <div class="progress-bar" id="progressBar" style="display:none">
            <div class="fill" id="progressFill"></div>
        </div>
        <button onclick="downloadSelected()">⬇ Download Selected</button>
    </div>
</div>

<script>
let allPosts = [];
let selectedIds = new Set();

function search() {
    const tags = document.getElementById('tagInput').value.trim();
    if (!tags) return;
    const limit = document.getElementById('limitInput').value || 100;

    document.getElementById('statusBar').textContent = 'Searching...';
    document.getElementById('gallery').innerHTML = '<div class="loading">Searching...</div>';

    fetch(`/api/search?tags=${encodeURIComponent(tags)}&limit=${limit}`)
        .then(r => r.json())
        .then(posts => {
            if (posts.error) { throw new Error(posts.error); }
            allPosts = posts;
            selectedIds.clear();
            renderGallery();
            document.getElementById('statusBar').textContent =
                `${posts.length} results for "${tags}"`;
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
                 onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 200 200%22><rect fill=%22%23111%22 width=%22200%22 height=%22200%22/><text fill=%22%23333%22 x=%2250%25%22 y=%2250%25%22 text-anchor=%22middle%22 dy=%22.3em%22>No Preview</text></svg>'" />
            <div class="meta">
                <span class="dims">${p.width}×${p.height}</span>
                <span class="rating ${p.rating}">${p.rating || '?'}</span>
            </div>
            <div class="tags">${(p.tags || []).slice(0, 6).join(' ')}</div>
        </div>
    `).join('');

    updateBottomBar();
}

function toggleCard(id, event) {
    if (selectedIds.has(id)) {
        selectedIds.delete(id);
    } else {
        selectedIds.add(id);
    }
    const card = document.querySelector(`.card[data-id="${id}"]`);
    if (card) card.classList.toggle('selected', selectedIds.has(id));
    const cb = card?.querySelector('.sel');
    if (cb) cb.checked = selectedIds.has(id);
    updateBottomBar();
}

function selectAll() {
    allPosts.forEach(p => selectedIds.add(p.id));
    renderGallery();
}

function deselectAll() {
    selectedIds.clear();
    renderGallery();
}

function updateBottomBar() {
    const bar = document.getElementById('bottomBar');
    document.getElementById('selectedCount').textContent = selectedIds.size;
    if (selectedIds.size > 0) {
        bar.classList.remove('hidden');
    } else {
        bar.classList.add('hidden');
    }
}

function downloadSelected() {
    if (selectedIds.size === 0) {
        alert('Select at least one image first.');
        return;
    }

    const bar = document.getElementById('progressBar');
    const fill = document.getElementById('progressFill');
    const status = document.getElementById('dlStatus');
    bar.style.display = 'block';
    fill.style.width = '0%';
    status.textContent = 'Starting...';

    fetch('/api/download', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ids: Array.from(selectedIds), mode: 'download'})
    })
    .then(r => r.json())
    .then(data => {
        if (data.error) throw new Error(data.error);
        pollProgress(data.download_id);
    })
    .catch(e => {
        status.textContent = 'Error: ' + e.message;
    });
}

function pollProgress(dlId) {
    const bar = document.getElementById('progressBar');
    const fill = document.getElementById('progressFill');
    const status = document.getElementById('dlStatus');

    const interval = setInterval(() => {
        fetch('/api/download/' + dlId)
            .then(r => r.json())
            .then(prog => {
                const pct = prog.total > 0 ? Math.round((prog.done / prog.total) * 100) : 0;
                fill.style.width = pct + '%';
                status.textContent = `${prog.done}/${prog.total} done (${prog.skipped} skip, ${prog.failed} fail)`;

                if (prog.status === 'complete') {
                    clearInterval(interval);
                    status.textContent += ' ✓ Complete!';
                    setTimeout(() => {
                        bar.style.display = 'none';
                        status.textContent = '';
                    }, 3000);
                }
            });
    }, 1000);
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
    init()
    print(f"║  Downloads → {download_dir}")
    print(f"║  Open     → http://localhost:8080   ║")
    print("╚══════════════════════════════════════╝")
    app.run(host="0.0.0.0", port=8080, debug=False)
