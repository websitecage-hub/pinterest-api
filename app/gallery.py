"""Visual gallery — a fast, app-like browser for the API's search results.

Served at /gallery. Self-contained HTML (no build step, no CDN dependencies).

Design notes worth keeping:
  * Media is rendered through the `/download?url=` CDN proxy, never
    `/pin/{id}/stream` — most search hits now carry opaque `e1_...` ids that do
    not resolve at `/pin/<id>/`, and the tile would show a broken image.
  * The grid drives the same public endpoints the API exposes, so what you see
    here is exactly what an API caller gets.
  * "Re-roll" uses /search?explore=true, which samples from a multi-page pool;
    plain pagination is deterministic, so repeat searches would look frozen.
"""

GALLERY_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pinterest Media — gallery</title>
<style>
  :root{
    --bg:#0e0f13; --panel:#161821; --panel2:#1d2030; --line:#272b3a;
    --text:#e9ecf3; --muted:#8b93a7; --accent:#e60023; --accent2:#ff4d6a;
    --ok:#3ddc84; --warn:#ffb020;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--text);
       font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif}
  a{color:inherit;text-decoration:none}
  header{position:sticky;top:0;z-index:40;background:rgba(14,15,19,.92);
         backdrop-filter:blur(10px);border-bottom:1px solid var(--line);padding:10px 14px}
  .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
  .brand{display:flex;align-items:center;gap:8px;font-weight:700;margin-right:4px}
  .dot{width:10px;height:10px;border-radius:50%;background:var(--accent)}
  .grow{flex:1;min-width:220px}
  input[type=search],select{background:var(--panel);border:1px solid var(--line);color:var(--text);
         border-radius:999px;padding:9px 14px;outline:none;font-size:14px}
  input[type=search]:focus{border-color:var(--accent2);box-shadow:0 0 0 3px rgba(230,0,35,.15)}
  .grow input{width:100%}
  button{background:var(--panel);border:1px solid var(--line);color:var(--text);
         border-radius:999px;padding:9px 14px;cursor:pointer;font-size:13px}
  button:hover{border-color:var(--accent2)}
  button.primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
  button.primary:hover{background:var(--accent2)}
  .tabs{display:flex;gap:4px;background:var(--panel);border:1px solid var(--line);border-radius:999px;padding:3px}
  .tabs button{background:none;border:none;border-radius:999px;padding:6px 13px;color:var(--muted)}
  .tabs button.on{background:var(--panel2);color:var(--text);font-weight:600}
  .switch{display:flex;align-items:center;gap:6px;color:var(--muted);cursor:pointer;user-select:none}
  .switch input{accent-color:var(--accent)}
  .status{color:var(--muted);font-size:12px;padding:8px 2px 0;display:flex;gap:12px;flex-wrap:wrap}
  .badge{border:1px solid var(--line);border-radius:999px;padding:2px 9px;font-size:11px}
  .badge.ok{color:var(--ok);border-color:rgba(61,220,132,.35)}
  .badge.anon{color:var(--warn);border-color:rgba(255,176,32,.35)}
  main{padding:14px}
  #grid{column-gap:12px;column-width:236px}
  .card{break-inside:avoid;margin:0 0 12px;border-radius:14px;overflow:hidden;background:var(--panel);
        position:relative;cursor:zoom-in}
  .card img,.card video{width:100%;display:block;background:#0a0b0f}
  .card .meta{position:absolute;inset:auto 0 0 0;padding:22px 10px 9px;font-size:12px;
        background:linear-gradient(transparent,rgba(0,0,0,.82));opacity:0;transition:.16s}
  .card:hover .meta{opacity:1}
  .card .meta .t{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .card .meta .s{color:#cfd4e2;margin-top:2px}
  .acts{position:absolute;top:8px;right:8px;display:flex;gap:6px;opacity:0;transition:.16s}
  .card:hover .acts{opacity:1}
  .acts button{background:rgba(0,0,0,.65);border:1px solid rgba(255,255,255,.18);padding:6px 9px;
        border-radius:9px;font-size:12px}
  .tag{position:absolute;top:8px;left:8px;background:rgba(0,0,0,.65);border-radius:8px;
       padding:3px 7px;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
  .skel{column-width:236px}
  .sk{border-radius:14px;background:linear-gradient(90deg,#161821,#1e2233,#161821);
      background-size:200% 100%;animation:sh 1.2s infinite;margin-bottom:12px;break-inside:avoid}
  @keyframes sh{0%{background-position:200% 0}100%{background-position:-200% 0}}
  .lightbox{position:fixed;inset:0;background:rgba(6,7,10,.95);display:none;z-index:80;
      padding:22px;overflow:auto}
  .lightbox.on{display:block}
  .lbwrap{max-width:1180px;margin:0 auto;display:grid;gap:16px;grid-template-columns:minmax(0,1.6fr) minmax(240px,.8fr)}
  @media(max-width:860px){.lbwrap{grid-template-columns:1fr}}
  .lbmedia img,.lbmedia video{width:100%;border-radius:14px;background:#000}
  .lbmeta h2{margin:0 0 6px;font-size:18px}
  .lbmeta p{color:var(--muted);margin:.4em 0}
  .lbmeta .btns{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
  .close{position:fixed;top:14px;right:16px;z-index:81}
  .toast{position:fixed;left:50%;bottom:22px;transform:translateX(-50%);background:#242838;
      border:1px solid var(--line);padding:9px 15px;border-radius:10px;opacity:0;transition:.2s;z-index:90}
  .toast.on{opacity:1}
  .err{border:1px solid rgba(230,0,35,.4);background:rgba(230,0,35,.08);color:#ffb3bd;
      padding:10px 13px;border-radius:10px;margin:10px 0;display:none}
  .more{text-align:center;padding:16px;color:var(--muted)}
  kbd{background:var(--panel2);border:1px solid var(--line);border-bottom-width:2px;border-radius:5px;
      padding:1px 5px;font-size:11px;color:var(--muted)}
</style>
</head>
<body>
<header>
  <div class="row">
    <div class="brand"><span class="dot"></span>Pinterest Media</div>
    <div class="grow"><input id="q" type="search" placeholder="Search anything…  ( / to focus )" autocomplete="off"></div>
    <button class="primary" id="go">Search</button>
    <button id="reroll" title="New results from a bigger pool (r)">↻ Re-roll</button>
  </div>
  <div class="row" style="margin-top:8px">
    <div class="tabs" id="tabs">
      <button data-media="all" class="on">All</button>
      <button data-media="video">Videos</button>
      <button data-media="gif">GIFs</button>
    </div>
    <select id="size" title="Results per search">
      <option>25</option><option selected>50</option><option>100</option>
    </select>
    <label class="switch" title="Sample from a multi-page pool so every search differs">
      <input type="checkbox" id="explore" checked> explore
    </label>
    <label class="switch" title="Fetch save/comment/repin counts (slower first load)">
      <input type="checkbox" id="stats" checked> stats
    </label>
    <span id="session" class="badge">session…</span>
  </div>
  <div class="status" id="status"></div>
</header>

<main>
  <div class="err" id="err"></div>
  <div id="grid"></div>
  <div class="more" id="more"></div>
</main>

<div class="lightbox" id="lb">
  <button class="close" id="lbclose">Close ✕</button>
  <div class="lbwrap">
    <div class="lbmedia" id="lbmedia"></div>
    <div class="lbmeta" id="lbmeta"></div>
  </div>
</div>
<div class="toast" id="toast"></div>

<script>
const $ = s => document.querySelector(s);
const state = { q:"", media:"all", size:50, stats:true, explore:true,
                bookmark:null, loading:false, items:[], idx:0, pool:0, pages:0 };

function toast(msg){ const t=$("#toast"); t.textContent=msg; t.classList.add("on");
  clearTimeout(t._h); t._h=setTimeout(()=>t.classList.remove("on"),1600); }
function showErr(msg){ const e=$("#err"); if(!msg){e.style.display="none";return;}
  e.textContent=msg; e.style.display="block"; }
const proxy = u => "/download?url=" + encodeURIComponent(u);

async function loadSession(){
  try{
    const d = await (await fetch("/session/status")).json();
    const el = $("#session");
    if(d.verified){ el.textContent = "personalized · " + (d.authenticated_as||"you");
      el.className = "badge ok"; }
    else if(d.authenticated){ el.textContent = "cookie rejected — anonymous";
      el.className = "badge anon"; }
    else { el.textContent = "anonymous"; el.className = "badge anon"; }
  }catch(e){ $("#session").textContent = "session unknown"; }
}

function skeletons(n){
  const g = $("#grid"); g.innerHTML = "";
  for(let i=0;i<n;i++){
    const d = document.createElement("div"); d.className="sk";
    d.style.height = (160 + Math.random()*220) + "px";
    g.appendChild(d);
  }
}

function endpoint(bookmark){
  const p = new URLSearchParams();
  p.set("q", state.q);
  p.set("page_size", state.size);
  if(state.explore){ p.set("explore","true"); p.set("pages","3"); }
  else if(bookmark){ p.set("page_bookmark", bookmark); }
  if(state.media === "video"){
    p.set("resolve_mp4","false");        // keep the grid fast; mp4 loads in the lightbox
    return "/search/videos?" + p;
  }
  if(state.media === "gif"){
    p.set("pages","3");
    return "/search/gifs?" + p;
  }
  if(state.stats) p.set("include_stats","true");
  return "/search?" + p;
}

async function search(append){
  if(state.loading || !state.q) return;
  state.loading = true;
  if(!append){ state.bookmark=null; state.items=[]; skeletons(12); }
  const t0 = performance.now();
  try{
    const r = await fetch(endpoint(append ? state.bookmark : null));
    const d = await r.json();
    if(!r.ok) throw new Error(d.detail || ("HTTP "+r.status));
    const items = d.results || [];
    const ms = Math.round(performance.now()-t0);
    state.bookmark = d.next_bookmark || null;
    state.pool = d.pool_size || 0; state.pages = d.pages_fetched || 0;
    state.items = append ? state.items.concat(items) : items;
    if(!append) $("#grid").innerHTML="";
    if(!append && !items.length){ $("#grid").innerHTML =
      '<p style="color:var(--muted)">No results for “'+esc(state.q)+'”.</p>'; }
    items.forEach(render);
    const bits = ["<b>"+d.hits+"</b> results",
      "<b>"+ms+"</b> ms",
      state.media.toUpperCase()];
    if(state.pool) bits.push("pool <b>"+state.pool+"</b> across "+state.pages+" pages");
    bits.push("cache: " + (state.explore?"off (explore)":"on"));
    $("#status").innerHTML = bits.join(" · ");
    $("#more").textContent = state.bookmark ? "scroll for more…" : "";
    showErr("");
  }catch(e){
    showErr("Search failed: " + e.message);
    $("#grid").innerHTML = ""; $("#status").innerHTML = "";
  }finally{ state.loading=false; }
}

function esc(s){ return (s||"").replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function render(p){
  const c = document.createElement("div");
  c.className = "card";
  const thumb = p.best_image || (p.images && (p.images["564x"]||p.images.orig)) || "";
  const isVid = p.type === "video";
  const mp4 = p.best_video || "";
  c.innerHTML =
    '<span class="tag">'+esc(p.type||"pin")+'</span>' +
    '<div class="acts">' +
      '<button class="dl" title="Download">↓</button>' +
      '<button class="cp" title="Copy media URL">⧉</button>' +
    '</div>' +
    '<img loading="lazy" src="'+proxy(thumb)+'" alt="'+esc(p.title||"")+'">' +
    '<div class="meta"><div class="t">'+esc(p.title||p.description||p.id||"")+'</div>' +
    '<div class="s">'+statsLine(p)+'</div></div>';
  if(isVid && mp4){
    const v = document.createElement("video");
    v.muted = true; v.loop = true; v.playsInline = true; v.preload="none"; v.src = proxy(mp4);
    c.addEventListener("mouseenter", ()=>{ c.querySelector("img").style.display="none";
      c.insertBefore(v, c.querySelector(".meta")); v.play().catch(()=>{}); });
    c.addEventListener("mouseleave", ()=>{ v.pause(); v.remove();
      c.querySelector("img").style.display="block"; });
  }
  c.querySelector(".dl").onclick = e => { e.stopPropagation();
    const u = (isVid && mp4) ? mp4 : thumb;
    const a = document.createElement("a"); a.href = proxy(u);
    a.download = ((p.title||p.id||"pin").slice(0,40)).replace(/[^\w.-]+/g,"_") + (isVid?".mp4":".jpg");
    document.body.appendChild(a); a.click(); a.remove(); toast("Downloading…"); };
  c.querySelector(".cp").onclick = async e => { e.stopPropagation();
    const u = (isVid && mp4) ? mp4 : thumb;
    try{ await navigator.clipboard.writeText(u); toast("Media URL copied"); }
    catch(_){ toast("Copy blocked by browser"); } };
  c.onclick = () => openLightbox(p);
  $("#grid").appendChild(c);
}

function statsLine(p){
  const parts = [];
  if(p.saves != null) parts.push("💾 " + p.saves);
  if(p.repins != null && p.repins) parts.push("↗ " + p.repins);
  if(p.reactions && p.reactions["1"] != null) parts.push("❤ " + p.reactions["1"]);
  if(p.creator) parts.push("@" + p.creator);
  if(p.creator_followers != null && p.creator_followers) parts.push(p.creator_followers + " followers");
  if(!parts.length) parts.push("id " + (p.id||"").slice(0,18));
  return parts.join(" · ");
}

async function openLightbox(p){
  state.idx = state.items.indexOf(p);
  const thumb = p.best_image || "";
  const isVid = p.type === "video";
  $("#lbmedia").innerHTML = isVid && p.best_video
    ? '<video src="'+proxy(p.best_video)+'" controls autoplay loop muted playsinline></video>'
    : '<img src="'+proxy(thumb)+'" alt="">';
  $("#lbmeta").innerHTML =
    "<h2>"+esc(p.title || p.description || "Untitled pin")+"</h2>" +
    "<p>"+statsLine(p)+"</p>" +
    '<p style="font-size:12px">'+esc((p.description||"").slice(0,400))+"</p>" +
    '<p style="font-size:12px">id <code>'+esc(p.id||"")+"</code></p>" +
    '<div class="btns">' +
      (isVid ? '<button id="getmp4">Get MP4</button>' : '') +
      '<a class="btn" href="'+proxy(isVid && p.best_video ? p.best_video : thumb)+'" download><button>↓ Download</button></a>' +
      (p.pin_url ? '<a href="'+esc(p.pin_url)+'" target="_blank" rel="noopener"><button>Open on Pinterest ↗</button></a>' : '') +
      '<button id="lbprev">← Prev</button><button id="lbnext">Next →</button>' +
    '</div>';
  $("#lb").classList.add("on");
  const mp4btn = $("#getmp4");
  if(mp4btn) mp4btn.onclick = async () => {
    mp4btn.textContent = "Resolving…";
    try{
      const d = await (await fetch("/pin/"+encodeURIComponent(p.id)+"/info")).json();
      if(d.best_video){
        $("#lbmedia").innerHTML = '<video src="'+proxy(d.best_video)+'" controls autoplay loop muted playsinline></video>';
        mp4btn.textContent = "MP4 loaded ✓";
      } else { mp4btn.textContent = "HLS-only pin — no MP4"; }
    }catch(e){ mp4btn.textContent = "No MP4 available"; }
  };
  $("#lbprev").onclick = ()=>step(-1);
  $("#lbnext").onclick = ()=>step(1);
}
function step(n){
  if(!state.items.length) return;
  state.idx = (state.idx + n + state.items.length) % state.items.length;
  openLightbox(state.items[state.idx]);
}
function closeLightbox(){ $("#lb").classList.remove("on"); $("#lbmedia").innerHTML=""; }

// --- wiring ---------------------------------------------------------------
$("#go").onclick = ()=>{ state.q = $("#q").value.trim(); syncUrl(); search(false); };
$("#q").addEventListener("keydown", e => { if(e.key==="Enter"){ state.q=$("#q").value.trim(); syncUrl(); search(false);} });
$("#reroll").onclick = ()=>{ if(!state.q){ $("#q").focus(); return; } search(false); };
$("#tabs").onclick = e => { const b=e.target.closest("button[data-media]"); if(!b) return;
  [...e.currentTarget.children].forEach(x=>x.classList.toggle("on", x===b));
  state.media = b.dataset.media; if(state.q) search(false); };
$("#size").onchange = e => { state.size = +e.target.value; if(state.q) search(false); };
$("#explore").onchange = e => { state.explore = e.target.checked; if(state.q) search(false); };
$("#stats").onchange = e => { state.stats = e.target.checked; if(state.q) search(false); };
$("#lbclose").onclick = closeLightbox;
$("#lb").onclick = e => { if(e.target.id === "lb") closeLightbox(); };
document.addEventListener("keydown", e => {
  const typing = /^(INPUT|SELECT|TEXTAREA)$/.test(document.activeElement.tagName);
  if(e.key === "/" && !typing){ e.preventDefault(); $("#q").focus(); }
  if(e.key === "Escape") closeLightbox();
  if(e.key === "r" && !typing) $("#reroll").click();
  if($("#lb").classList.contains("on")){
    if(e.key === "ArrowLeft") step(-1);
    if(e.key === "ArrowRight") step(1);
  }
});
// infinite scroll (only in paged mode — explore returns a fresh sample instead)
const io = new IntersectionObserver(es => {
  if(es.some(x=>x.isIntersecting) && state.bookmark && !state.explore && !state.loading){
    search(true);
  }
}, { rootMargin: "800px" });
io.observe($("#more"));

function syncUrl(){
  const p = new URLSearchParams();
  if(state.q) p.set("q", state.q);
  if(state.media!=="all") p.set("media", state.media);
  if(state.size!==50) p.set("size", state.size);
  if(!state.explore) p.set("explore","false");
  history.replaceState(null,"", "/gallery" + (p.toString()?"?"+p:""));
}

// boot
(function(){
  const p = new URLSearchParams(location.search);
  const q = p.get("q") || "";
  if(p.get("media")) state.media = p.get("media");
  if(p.get("size")) state.size = +p.get("size");
  if(p.get("explore") === "false") state.explore = false;
  $("#size").value = String(state.size);
  $("#explore").checked = state.explore;
  $("#stats").checked = state.stats;
  [...$("#tabs").children].forEach(b=>b.classList.toggle("on", b.dataset.media===state.media));
  $("#q").value = q; state.q = q;
  loadSession();
  if(q) search(false);
  else { $("#status").innerHTML = "Type a query — <kbd>/</kbd> focuses the box, <kbd>r</kbd> re-rolls, <kbd>Esc</kbd> closes."; }
})();
</script>
</body>
</html>
"""


def register_gallery(app):
    """Mount GET /gallery on the FastAPI app."""

    @app.get("/gallery", include_in_schema=False)
    def gallery():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(GALLERY_HTML)
