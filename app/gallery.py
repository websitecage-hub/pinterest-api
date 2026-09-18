"""Visual gallery — one page that runs the asset queries and shows results."""
from fastapi.responses import HTMLResponse

GALLERY_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Pinterest API — Asset Run</title>
<style>
body{font-family:system-ui,sans-serif;background:#0e1116;color:#e6e9ef;margin:0;padding:24px}
h1{font-size:20px} h2{font-size:15px;margin:28px 0 10px;color:#9fb0c7}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:10px}
.card{background:#161b24;border-radius:8px;overflow:hidden;position:relative}
.card img,.card video{width:100%;height:170px;object-fit:cover;display:block}
.tag{position:absolute;top:6px;left:6px;background:#238636;color:#fff;font-size:11px;padding:2px 7px;border-radius:10px}
.err{color:#f85149;font-size:13px}
</style></head><body>
<h1>Pinterest Media API — asset run (aesthetic · motivational · background)</h1>
<div id="out"></div>
<script>
const QUERIES = ["aesthetic wallpaper","motivational quotes background","aesthetic background",
                 "motivational gym wallpaper","sunset aesthetic","desktop background 4k"];
const out = document.getElementById("out");
(async () => {
  for (const q of QUERIES) {
    const h2 = document.createElement("h2"); h2.textContent = "q: " + q;
    const grid = document.createElement("div"); grid.className = "grid";
    out.append(h2, grid);
    try {
      const r = await fetch(`/search?q=${encodeURIComponent(q)}&page_size=12`);
      const d = await r.json();
      h2.textContent = `q: ${q} — ${d.hits} hits`;
      for (const pin of d.results) {
        const c = document.createElement("div"); c.className = "card";
        const tag = document.createElement("span"); tag.className = "tag";
        tag.textContent = pin.type; c.append(tag);
        if (pin.type === "video" && pin.best_video) {
          const v = document.createElement("video");
          v.src = `/pin/${pin.id}/stream`; v.muted = true; v.loop = true;
          v.setAttribute("playsinline",""); v.onmouseover=()=>v.play(); v.onmouseout=()=>v.pause();
          c.append(v);
        } else if (pin.best_image) {
          const im = document.createElement("img"); im.loading = "lazy";
          im.src = `/pin/${pin.id}/stream`; im.alt = pin.title || "";
          im.onerror = () => { im.remove(); }; c.append(im);
        } else { c.remove(); continue; }
        c.title = `${pin.title || ""} — ${pin.pin_url}`;
        c.onclick = () => window.open(pin.pin_url, "_blank");
        c.style.cursor = "pointer";
        grid.append(c);
      }
    } catch (e) {
      const er = document.createElement("div"); er.className = "err";
      er.textContent = `q: ${q} — search failed: ${e}`; out.append(er);
    }
  }
})();
</script></body></html>"""


def register_gallery(app):
    @app.get("/gallery", response_class=HTMLResponse)
    def gallery():
        return GALLERY_HTML
