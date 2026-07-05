"""Single-file live operations dashboard served same-origin at GET /ops.

Unlike the server-rendered /dashboard (static snapshot with meta-refresh), this is a
small client-side SPA that polls the gateway JSON API (/api/v1/dashboard, /metrics,
/tool-audit) on an interval and re-renders without a full page reload. Served from the
gateway itself so it shares an origin with the API (no CORS configuration required).

An optional API key (for deployments with auth enabled) is entered in the header and
stored in localStorage, then sent as the X-API-Key header on every request.
"""

from __future__ import annotations

OPS_DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ClawCam — Live Ops</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  :root {
    --bg:#0f1419; --panel:#1a212b; --panel2:#222b38; --line:#2d3848;
    --txt:#e6edf3; --muted:#8b98a9; --accent:#4ea1ff; --good:#3fb950;
    --warn:#d29922; --bad:#f85149; --chip:#2d3848;
  }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--txt);
         font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; }
  header { display:flex; align-items:center; gap:16px; padding:14px 20px;
           background:var(--panel); border-bottom:1px solid var(--line); position:sticky; top:0; z-index:5; }
  header h1 { font-size:16px; margin:0; letter-spacing:.3px; }
  header .gw { color:var(--muted); font-size:12px; }
  header .spacer { flex:1; }
  header input { background:var(--panel2); border:1px solid var(--line); color:var(--txt);
                 border-radius:6px; padding:6px 8px; font-size:12px; width:180px; }
  header button { background:var(--accent); border:0; color:#04121f; font-weight:600;
                  border-radius:6px; padding:7px 12px; cursor:pointer; font-size:12px; }
  header .status { font-size:12px; color:var(--muted); min-width:120px; text-align:right; }
  main { padding:20px; max-width:1280px; margin:0 auto; }
  .kpis { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:20px; }
  .kpi { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:14px 16px; }
  .kpi .n { font-size:28px; font-weight:700; }
  .kpi .l { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.5px; margin-top:2px; }
  .kpi.bad .n { color:var(--bad); }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:16px; }
  @media (max-width:880px){ .grid { grid-template-columns:1fr; } }
  .panel { background:var(--panel); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:16px; }
  .panel h2 { font-size:13px; margin:0 0 12px; color:var(--muted); text-transform:uppercase; letter-spacing:.5px; }
  table { width:100%; border-collapse:collapse; font-size:13px; }
  th,td { text-align:left; padding:7px 8px; border-bottom:1px solid var(--line); }
  th { color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; }
  td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .chip { display:inline-block; background:var(--chip); border-radius:20px; padding:2px 9px; font-size:12px; }
  .pill-good{color:var(--good)} .pill-warn{color:var(--warn)} .pill-bad{color:var(--bad)}
  .empty { color:var(--muted); font-style:italic; padding:8px; }
  canvas { max-height:240px; }
  .err { background:#3a1212; border:1px solid var(--bad); color:#ffb4ad; padding:10px 14px;
         border-radius:8px; margin-bottom:16px; display:none; }
</style>
</head>
<body>
<header>
  <h1>🐾 ClawCam <span class="gw" id="gw"></span></h1>
  <div class="spacer"></div>
  <input id="apikey" placeholder="API key (if auth on)" autocomplete="off">
  <label class="gw"><input type="checkbox" id="auto" checked> auto</label>
  <button id="refresh">Refresh</button>
  <div class="status" id="status">—</div>
</header>
<main>
  <div class="err" id="err"></div>
  <div class="kpis" id="kpis"></div>
  <div class="grid">
    <div class="panel"><h2>Top species</h2><canvas id="speciesChart"></canvas><div id="speciesEmpty" class="empty" style="display:none">No detections yet.</div></div>
    <div class="panel"><h2>Detection labels</h2><canvas id="labelChart"></canvas><div id="labelEmpty" class="empty" style="display:none">No detections yet.</div></div>
  </div>
  <div class="panel"><h2>Device health</h2><div id="devices"></div></div>
  <div class="panel"><h2>Tool-call funnel (audit)</h2><div id="tools"></div></div>
  <div class="panel"><h2>Recent detections</h2><div id="detections"></div></div>
</main>
<script>
const $ = id => document.getElementById(id);
const KEY = "clawcam_ops_apikey";
$("apikey").value = localStorage.getItem(KEY) || "";
$("apikey").addEventListener("change", e => localStorage.setItem(KEY, e.target.value.trim()));

let speciesChart, labelChart;

function headers() {
  const k = ($("apikey").value || "").trim();
  return k ? { "X-API-Key": k } : {};
}
async function getJSON(path) {
  const r = await fetch(path, { headers: headers() });
  if (!r.ok) throw new Error(path + " → HTTP " + r.status);
  return r.json();
}
function esc(s){ return String(s==null?"":s).replace(/[&<>]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;"}[c])); }
function pct(v){ return v==null?"—":v+"%"; }
function battClass(p){ return p==null?"":p<20?"pill-bad":p<50?"pill-warn":"pill-good"; }

function kpis(m){
  const c = m.counts||{}, t = m.tool_calls||{};
  const cards = [
    ["Devices", c.devices??0, false],
    ["Events", c.events??0, false],
    ["Detections", c.inference_results??0, false],
    ["Alerts fired", c.alerts_fired??0, false],
    ["Tool calls", t.total??0, false],
    ["Tool errors", t.errors??0, (t.errors??0)>0],
  ];
  $("kpis").innerHTML = cards.map(([l,n,bad])=>
    `<div class="kpi${bad?' bad':''}"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
}
function barChart(existing, canvasId, emptyId, obj, color){
  const labels = Object.keys(obj||{}), data = labels.map(k=>obj[k]);
  $(emptyId).style.display = labels.length ? "none" : "block";
  if (existing) existing.destroy();
  if (!labels.length) return null;
  return new Chart($(canvasId), {
    type:"bar",
    data:{ labels, datasets:[{ data, backgroundColor:color, borderRadius:4 }] },
    options:{ plugins:{legend:{display:false}}, scales:{
      x:{ticks:{color:"#8b98a9"},grid:{display:false}},
      y:{ticks:{color:"#8b98a9",precision:0},grid:{color:"#2d3848"},beginAtZero:true} } }
  });
}
function devices(d){
  const rows = (d.devices||[]).map(dev=>{
    const h = (d.health_by_device||{})[dev.device_id] || {};
    const b = (h.battery||{}); const st = (h.storage||{});
    const freeMB = st.free_bytes!=null ? Math.round(st.free_bytes/1048576) : null;
    return `<tr><td>${esc(dev.device_id)}</td><td>${esc(dev.name||"")}</td>
      <td class="num ${battClass(b.percentage)}">${pct(b.percentage)}</td>
      <td class="num">${b.voltage!=null?b.voltage.toFixed(2)+"V":"—"}</td>
      <td class="num">${freeMB!=null?freeMB+" MB":"—"}</td>
      <td>${esc(h.status||"—")}</td></tr>`;
  }).join("");
  $("devices").innerHTML = rows
    ? `<table><thead><tr><th>Device</th><th>Name</th><th class="num">Battery</th><th class="num">Voltage</th><th class="num">Free</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">No devices registered.</div>`;
}
function tools(m){
  const by = (m.tool_calls&&m.tool_calls.by_tool)||[];
  const rows = by.map(t=>{
    const errs = t.errors||0;
    const avg = t.avg_duration_ms!=null ? Math.round(t.avg_duration_ms)+" ms" : "—";
    return `<tr><td>${esc(t.tool_name||t.tool||"?")}</td>
      <td class="num">${t.calls??0}</td>
      <td class="num ${errs>0?'pill-bad':''}">${errs}</td>
      <td class="num">${avg}</td></tr>`;
  }).join("");
  $("tools").innerHTML = rows
    ? `<table><thead><tr><th>Tool</th><th class="num">Calls</th><th class="num">Errors</th><th class="num">Avg latency</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">No tool calls recorded yet.</div>`;
}
function detections(d){
  const rows = (d.recent_detections||[]).slice(0,20).map(r=>{
    const conf = r.top_confidence!=null ? (r.top_confidence*100).toFixed(0)+"%" : "—";
    return `<tr><td>${esc(r.event_id||"")}</td><td><span class="chip">${esc(r.top_label||"—")}</span></td>
      <td>${esc(r.top_species||"—")}</td><td class="num">${conf}</td><td>${esc(r.model_name||"")}</td></tr>`;
  }).join("");
  $("detections").innerHTML = rows
    ? `<table><thead><tr><th>Event</th><th>Label</th><th>Species</th><th class="num">Conf.</th><th>Model</th></tr></thead><tbody>${rows}</tbody></table>`
    : `<div class="empty">No detections yet.</div>`;
}

async function refresh(){
  try {
    $("status").textContent = "loading…";
    const [d, m] = await Promise.all([ getJSON("/api/v1/dashboard"), getJSON("/api/v1/metrics") ]);
    $("gw").textContent = d.gateway_id ? "· " + d.gateway_id : "";
    kpis(m);
    speciesChart = barChart(speciesChart, "speciesChart", "speciesEmpty", d.detection_species_counts, "#4ea1ff");
    labelChart   = barChart(labelChart,   "labelChart",   "labelEmpty",   d.detection_label_counts,   "#3fb950");
    devices(d); tools(m); detections(d);
    $("err").style.display = "none";
    $("status").textContent = "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    $("err").style.display = "block";
    $("err").textContent = "Fetch failed: " + e.message + " — check the gateway is running and the API key (if auth is enabled).";
    $("status").textContent = "error";
  }
}
$("refresh").addEventListener("click", refresh);
let timer = setInterval(()=>{ if($("auto").checked) refresh(); }, 15000);
refresh();
</script>
</body>
</html>
"""


def render_ops_dashboard() -> str:
    """Return the standalone live ops dashboard HTML (served at GET /ops)."""
    return OPS_DASHBOARD_HTML
