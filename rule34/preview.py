"""HTML preview gallery generator for rule34 search results.

Produces a static HTML page with a responsive grid of thumbnails.
Each thumbnail links to the full image. Checkboxes allow selective download.
"""

from pathlib import Path
from typing import Optional
from rule34.api import Post

GALLERY_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Rule34 Search: {title}</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        background: #0d0d0d;
        color: #ccc;
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
        padding: 20px;
    }}
    .header {{
        position: sticky; top: 0; z-index: 100;
        background: #0d0d0dee; backdrop-filter: blur(12px);
        padding: 16px 20px; margin: -20px -20px 20px -20px;
        border-bottom: 1px solid #222;
        display: flex; align-items: center; justify-content: space-between;
        flex-wrap: wrap; gap: 12px;
    }}
    .header h1 {{ font-size: 1.1rem; color: #eee; }}
    .header .tags {{ color: #a78bfa; font-size: 0.9rem; }}
    .header .count {{ color: #666; font-size: 0.85rem; }}
    .actions {{ display: flex; gap: 10px; align-items: center; }}
    .btn {{
        padding: 8px 16px; border: 1px solid #333; border-radius: 6px;
        background: #1a1a1a; color: #ccc; cursor: pointer;
        font-size: 0.85rem; transition: all 0.15s;
    }}
    .btn:hover {{ background: #2a2a2a; border-color: #555; }}
    .btn.primary {{ background: #7c3aed; border-color: #7c3aed; color: #fff; }}
    .btn.primary:hover {{ background: #6d28d9; }}
    .gallery {{
        display: grid;
        grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
        gap: 12px;
    }}
    .card {{
        position: relative;
        background: #141414;
        border: 1px solid #1f1f1f;
        border-radius: 8px;
        overflow: hidden;
        transition: border-color 0.15s, transform 0.15s;
    }}
    .card:hover {{ border-color: #444; transform: translateY(-2px); }}
    .card.selected {{ border-color: #7c3aed; box-shadow: 0 0 12px #7c3aed33; }}
    .card input[type="checkbox"] {{
        position: absolute; top: 8px; left: 8px; z-index: 10;
        width: 20px; height: 20px; accent-color: #7c3aed;
        cursor: pointer;
    }}
    .card a {{ display: block; text-decoration: none; color: inherit; }}
    .card img {{
        width: 100%; height: 200px; object-fit: cover;
        display: block; background: #1a1a1a;
    }}
    .card .info {{
        padding: 8px 10px; font-size: 0.75rem;
        display: flex; justify-content: space-between; align-items: center;
    }}
    .card .info .dims {{ color: #666; }}
    .card .info .rating {{
        padding: 1px 6px; border-radius: 3px;
        font-size: 0.7rem; font-weight: 600; text-transform: uppercase;
    }}
    .card .info .rating.e {{ background: #dc2626; color: #fff; }}
    .card .info .rating.q {{ background: #f59e0b; color: #000; }}
    .card .info .rating.s {{ background: #16a34a; color: #fff; }}
    .card .info .rating.g {{ background: #2563eb; color: #fff; }}
    .card .tags {{
        padding: 0 10px 8px; font-size: 0.7rem; color: #555;
        overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    }}
    .selected-bar {{
        position: fixed; bottom: 0; left: 0; right: 0;
        background: #1a1a1aee; backdrop-filter: blur(12px);
        border-top: 1px solid #333; padding: 12px 20px;
        display: flex; align-items: center; justify-content: space-between;
        z-index: 200;
    }}
    .selected-bar.hidden {{ display: none; }}
    .selected-bar .count {{ color: #a78bfa; font-weight: 600; }}
    .download-cmd {{
        background: #0d0d0d; border: 1px solid #333; border-radius: 6px;
        padding: 8px 12px; color: #a78bfa; font-family: 'SF Mono', 'Fira Code', monospace;
        font-size: 0.8rem; max-width: 600px; overflow-x: auto; white-space: nowrap;
    }}
</style>
</head>
<body>
<div class="header">
    <div>
        <h1>Rule34 Search Results</h1>
        <div class="tags">Tags: {tags_display}</div>
        <div class="count">{count} results</div>
    </div>
    <div class="actions">
        <button class="btn" onclick="selectAll()">Select All</button>
        <button class="btn" onclick="deselectAll()">Deselect None</button>
        <button class="btn primary" onclick="copyDownloadCmd()">📋 Copy Download Command</button>
    </div>
</div>
<div class="gallery">
    {cards}
</div>
<div class="selected-bar hidden" id="selectedBar">
    <span><span class="count" id="selectedCount">0</span> selected</span>
    <div class="download-cmd" id="downloadCmd"></div>
    <button class="btn" onclick="copyDownloadCmd()">📋 Copy</button>
</div>
<script>
    const allIds = {all_ids};
    function updateBar() {{
        const checked = document.querySelectorAll('.card input:checked');
        const ids = Array.from(checked).map(cb => cb.value);
        const bar = document.getElementById('selectedBar');
        document.getElementById('selectedCount').textContent = ids.length;
        if (ids.length > 0) {{
            bar.classList.remove('hidden');
            document.getElementById('downloadCmd').textContent =
                'r34 download --ids ' + ids.join(',');
        }} else {{
            bar.classList.add('hidden');
        }}
    }}
    function selectAll() {{
        document.querySelectorAll('.card input').forEach(cb => {{ cb.checked = true; cb.closest('.card').classList.add('selected'); }});
        updateBar();
    }}
    function deselectAll() {{
        document.querySelectorAll('.card input').forEach(cb => {{ cb.checked = false; cb.closest('.card').classList.remove('selected'); }});
        updateBar();
    }}
    function copyDownloadCmd() {{
        const ids = Array.from(document.querySelectorAll('.card input:checked')).map(cb => cb.value);
        if (ids.length === 0) {{ alert('Select at least one image first.'); return; }}
        const cmd = 'r34 download --ids ' + ids.join(',');
        navigator.clipboard.writeText(cmd).then(() => {{
            const btn = document.querySelector('.btn.primary');
            const orig = btn.textContent;
            btn.textContent = '✓ Copied!';
            setTimeout(() => btn.textContent = orig, 1500);
        }});
    }}
    document.querySelectorAll('.card input').forEach(cb => {{
        cb.addEventListener('change', function() {{
            this.closest('.card').classList.toggle('selected', this.checked);
            updateBar();
        }});
    }});
</script>
</body>
</html>
"""


def generate_gallery(
    posts: list[Post],
    tags: list[str],
    output_path: Optional[Path] = None,
) -> Path:
    """Generate an HTML preview gallery for search results.

    Args:
        posts: Search results to display.
        tags: The tags that were searched.
        output_path: Where to save the HTML. Defaults to ./rule34_gallery.html.

    Returns:
        Path to the generated HTML file.
    """
    if output_path is None:
        output_path = Path("rule34_gallery.html")

    cards = []
    for post in posts:
        tags_preview = " ".join(post.tag_list[:6])
        cards.append(
            f"""<div class="card">
    <input type="checkbox" value="{post.id}" />
    <a href="{post.file_url}" target="_blank">
        <img src="{post.preview_url}" alt="Post {post.id}" loading="lazy" />
    </a>
    <div class="info">
        <span class="dims">{post.width}×{post.height}</span>
        <span class="rating {post.rating[0].lower() if post.rating else 'u'}">{post.rating}</span>
    </div>
    <div class="tags">{tags_preview}</div>
</div>"""
        )

    html = GALLERY_TEMPLATE.format(
        title=" ".join(tags),
        tags_display=" ".join(tags),
        count=len(posts),
        cards="\n".join(cards),
        all_ids=[p.id for p in posts],
    )

    output_path.write_text(html)
    return output_path
