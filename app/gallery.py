"""Visual gallery — search the API and see the results as a grid, for any query.

Media is rendered through the `/download?url=` CDN proxy rather than
`/pin/{id}/stream`, because Pinterest's search surface now returns opaque
"e1_..." ids for most hits and those do not resolve at /pin/<id>/ (404).
The CDN URL in `best_image` / `best_video` / `images.*` works for both
numeric and opaque ids.
"""
from fastapi.responses import HTMLResponse

GALLERY_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>Pinterest Media API — gallery</title>
<style>
:root{color-scheme:dark}
body{font-family:system-ui,sans-serif;background:#0e1116;color:#e6e9ef;margin:0;padding:24px}
h1{font-size:20px;margin:0 0 4px}
.sub{color:#8b9bb4;font-size:13px;margin-bottom:18px}
form{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:8px}
input[type=text]{flex:1;min-width:240px;background:#161b24;border:1px solid #2a3442;color:#e6e9ef;
  padding:10px 12px;border-radius:8px;font-size:14px}
select{background:#161b24;border:1px solid #2a3442;color:#e6e9ef;padding:10px;border-radius:8px}
button{background:#238636;border:0;color:#fff;padding:10px 18px;border-radius:8px;font-size:14px;cursor:pointer}
button:disabled{opacity:.5;cursor:default}
#stat{color:#8b9bb4;font-size:13px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:10px}
.card{background:#161b24;border-radius:8px;overflow:hidden;position:relative;cursor:pointer}
.card img,.card video{width:100%;height:190px;object-fit:cover;display:block;background:#0b0e13}
.tag{position:absolute;top:6px;left:6px;background:#238636;color:#fff;font-size:11px;
  padding:2px 7px;border-radius:10px;z-index:2}
.tag.v{background:#8957e5}
.tag.g{background:#bf8700}
.tag.o{background:#57606a}
.meta{position:absolute;bottom:0;left:0;right:0;padding:6px 8px;font-size:11px;color:#cdd9e5;
  background:linear-gradient(transparent,rgba(0,0,0,.85));white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.err{color:#f85149;font-size:13px;margin:6px 0}
</style></head><body>
<h1>Pinterest Media API — gallery</h1>
<div class="sub">Any query. Media proxied from the pinimg CDN, so opaque-id results render too.</div>
<form id="f">
  <input type="text" id="q" placeholder="e.g. aesthetic wallpaper" autocomplete="off" autofocus>
  <select id="mt">
    <option value="any">any</option>
    <option value="video">video only</option>
    <option value="gif">gif only</option>
  </select>
  <select id="ps">
    <option value="12">12</option>
    <option value="25" selected>25</option>
    <option value="50">50</option>
    <option value="100">100</option>
  </select>
  <button type="submit" id="go">Search</button>
</form>
<div id="stat"></div>
<div class="grid" id="grid"></div>
<script>
const $ = (id) => document.getElementById(id);
const CDN = (u, inline) => `/download?url=${encodeURIComponent(u)}&inline=${inline ? "true" : "false"}`;

function clear() { $("grid").replaceChildren(); }

async function run(q, media, size) {
  clear();
  const go = $("go"); go.disabled = true;
  $("stat").textContent = `searching "${q}" …`;
  try {
    const p = new URLSearchParams({ q, page_size: size });
    // media routes use the dedicated endpoints: /search/videos uses Pinterest's
    // server-side video scope, /search/gifs runs the gif-oriented query + probing.
    // (media_type= on /search only filters the "pins" scope client-side, which
    // misses most videos and nearly all gifs.)
    let path = "/search";
    if (media === "video") path = "/search/videos";
    else if (media === "gif") { path = "/search/gifs"; p.set("pages", "3"); p.delete("page_size"); }
    else p.set("resolve_mp4", "true");
    const t0 = performance.now();
    const d = await (await fetch(`${path}?${p}`)).json();
    const ms = Math.round(performance.now() - t0);
    if (d.detail) throw new Error(JSON.stringify(d.detail));
    $("stat").textContent = `${d.hits} hits for "${d.query}" in ${ms} ms`
      + (d.effective_query && d.effective_query !== d.query ? ` (effective: ${d.effective_query})` : "")
      + (d.next_bookmark ? ` — has_more: true, next_bookmark: ${d.next_bookmark.slice(0, 18)}…` : "");
    let shown = 0;
    for (const pin of d.results) {
      const opaque = !/^\\d+$/.test(pin.id);
      const c = document.createElement("div"); c.className = "card";
      const tag = document.createElement("span");
      tag.className = "tag" + (pin.type === "video" ? " v" : pin.type === "gif" ? " g" : "");
      tag.textContent = pin.type; c.append(tag);
      if (opaque) {
        const o = document.createElement("span");
        o.className = "tag o"; o.style.left = "auto"; o.style.right = "6px"; o.textContent = "opaque id";
        c.append(o);
      }
      if (pin.type === "video" && pin.best_video) {
        const v = document.createElement("video");
        v.src = CDN(pin.best_video, true); v.muted = true; v.loop = true; v.preload = "none";
        v.setAttribute("playsinline", "");
        v.onmouseover = () => v.play().catch(() => {}); v.onmouseout = () => v.pause();
        c.append(v);
      } else if (pin.best_image) {
        const im = document.createElement("img"); im.loading = "lazy";
        im.src = CDN(pin.best_image, true); im.alt = pin.title || "";
        im.onerror = () => { im.remove(); };
        c.append(im);
      } else { continue; }
      const m = document.createElement("div"); m.className = "meta";
      m.textContent = (pin.creator ? "@" + pin.creator + " · " : "") + (pin.title || pin.id);
      c.append(m);
      c.title = (pin.title || "") + " — " + pin.pin_url + "\\n" + pin.id;
      c.onclick = () => window.open(pin.pin_url, "_blank");
      $("grid").append(c); shown++;
    }
    if (!shown) $("stat").textContent += " — no renderable media in this page";
  } catch (e) {
    const er = document.createElement("div"); er.className = "err";
    er.textContent = `search failed: ${e}`;
    $("stat").textContent = ""; $("stat").append(er);
  } finally { go.disabled = false; }
}

$("f").onsubmit = (ev) => {
  ev.preventDefault();
  const q = $("q").value.trim();
  if (q) { history.replaceState(null, "", `?q=${encodeURIComponent(q)}`); run(q, $("mt").value, $("ps").value); }
};
const init = new URLSearchParams(location.search).get("q");
if (init) { $("q").value = init; run(init, "any", "25"); }
</script></body></html>"""


def register_gallery(app):
    @app.get("/gallery", response_class=HTMLResponse)
    def gallery():
        return GALLERY_HTML