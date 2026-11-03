
const $ = (s) => document.querySelector(s);
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const NEUTRAL = new THREE.Color(0x7d8892), AMBER = new THREE.Color(0xe3a72f), RED = new THREE.Color(0xe0483a), DARK = new THREE.Color(0x474f57);
const ROAD_W = 1.5;  // exaggerated for visibility (a real carriageway pair is about 0.03 km wide)

let cfg = null, state = null, selected = 0, layer = 'cond', showTruth = false, token = '', histTimer = 0;
const segMesh = [], segMid = [], segDir = [], trucks = new Map();

/* ---------------------------------------------------------------- helpers */
function setHtml(el, html) { if (el._h !== html) { el._h = html; el.innerHTML = html; } }
const fmt = (v, d = 1) => (v === null || v === undefined || Number.isNaN(v) ? '-' : Number(v).toFixed(d));
const sid = (i) => 'S' + String(i + 1).padStart(2, '0');
let toastTimer = 0;
function toast(msg) { const b = $('#toast'); b.textContent = msg; b.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { b.hidden = true; }, 5000); }
async function post(path, body) {
  const h = { 'Content-Type': 'application/json' };
  if (token) h['X-Operator-Token'] = token;
  const r = await fetch(path, { method: 'POST', headers: h, body: JSON.stringify(body || {}) });
  if (!r.ok) { let t = r.statusText; try { t = (await r.json()).detail || t; } catch (e) {} toast('Request refused: ' + (typeof t === 'string' ? t : JSON.stringify(t))); }
  return r.ok;
}
function condColor(ci) {
  if (ci >= 65) return NEUTRAL.clone();
  if (ci >= 45) return NEUTRAL.clone().lerp(AMBER, (65 - ci) / 20);
  return AMBER.clone().lerp(RED, Math.min(1, (45 - ci) / 25));
}
function statusColor(st) { return st === 'red' ? RED : st === 'amber' ? AMBER : st === 'unknown' ? DARK : NEUTRAL; }
const cls = (ci) => (ci < 45 ? 'red' : ci < 65 ? 'amber' : '');

/* ---------------------------------------------------------------- runs and scenarios */
const DEFAULT_SCEN = [{ kind: 'rain', label: 'Heavy rain', detail: '24 h at 8 mm/h' }, { kind: 'overload', label: 'Overloaded trucks', detail: '7 days, gross weight +35%' },
  { kind: 'closure', label: 'Road closure', detail: '4 h, selected segment', segment: true }, { kind: 'accident', label: 'Accident', detail: '3 h, selected segment', segment: true }, { kind: 'sensor_outage', label: 'Sensor outage', detail: 'selected segment', segment: true }];
const catalog = () => cfg.scenarios || DEFAULT_SCEN;
const SEGKIND = ['closure', 'accident', 'sensor_outage'];
function scenBody(kind, seg) {
  if (cfg.runs) return SEGKIND.includes(kind) ? { kind, segment_id: seg } : { kind };
  return { rain: { kind, hours: 24, intensity: 8 }, overload: { kind, mult: 1.35, days: 7 }, closure: { kind, segment_id: seg, hours: 4 }, accident: { kind, segment_id: seg, hours: 3 }, sensor_outage: { kind, segment_id: seg, ticks: 60 } }[kind];
}
function renderScenMenu() {
  const act = (state.run && state.run.scenarios) || [], max = cfg.max_scenarios || 99, full = act.length >= max;
  $('#scenSummary').textContent = cfg.runs ? `Scenarios ${act.length} of ${max}` : 'Scenarios';
  setHtml($('#scenBody'), catalog().map((c) => `<button class="scen-item" data-kind="${c.kind}" ${full || act.some((a) => a.kind === c.kind) ? 'disabled' : ''}>${c.label}<small>${c.detail}${c.segment ? ' (uses the selected segment)' : ''}</small></button>`).join('') +
    (full ? `<small>A maximum of ${max} scenarios can be active at once.</small>` : ''));
}
function renderRunbar() {
  if (!cfg.runs || !state.run) { $('#runbar').textContent = ''; return; }
  const r = state.run, t = (h) => (h >= 48 ? (h / 24).toFixed(1) + ' d' : Math.max(1, Math.round(h)) + ' h');
  $('#runbar').innerHTML = `Run <b title="Enter this seed when starting a simulation to repeat this run">${r.seed}</b>` + (state.control.paused ? ' <span class="paused">PAUSED</span>' : '') + ' · ' +
    (r.scenarios.length ? `Scenarios ${r.scenarios.length} of ${r.max}: ` + r.scenarios.map((s) => `<b>${s.label}</b> (${t(s.remaining_h)} left)`).join(', ') : 'No scenario active');
}
function openSetup() {
  const dlg = $('#setup'); if (dlg.open) return;
  const seg = '<option value="random">Random segment</option>' + cfg.segments.map((s) => `<option value="${s.id}">${sid(s.id)}</option>`).join('');
  dlg.innerHTML = `<form id="setupForm"><h2 id="setupTitle">Start a simulation</h2>
    <p class="note">Choose up to three scenarios to run together, or none for a normal-conditions run. Each run starts from a new random road: different worn sections and potholes.</p>
    <fieldset><legend class="sr">Scenarios</legend>${catalog().map((c) => `<label class="scn"><input type="checkbox" name="scn" value="${c.kind}"><span><b>${c.label}</b><small>${c.detail}</small></span>${c.segment ? `<select data-for="${c.kind}" aria-label="${c.label}: segment">${seg}</select>` : '<span></span>'}</label>`).join('')}</fieldset>
    <p class="note" id="scnCount" aria-live="polite">0 of ${cfg.max_scenarios} selected</p>
    <label class="seedrow">Seed (optional) <input id="seedIn" inputmode="numeric" placeholder="random"></label>
    <div class="btnrow"><button type="submit" class="primary">Start simulation</button></div></form>`;
  const boxes = [...dlg.querySelectorAll('input[name=scn]')];
  boxes.forEach((b) => b.onchange = () => { const n = boxes.filter((x) => x.checked).length; boxes.forEach((x) => { x.disabled = !x.checked && n >= cfg.max_scenarios; }); $('#scnCount').textContent = `${n} of ${cfg.max_scenarios} selected` + (n >= cfg.max_scenarios ? ' (maximum)' : ''); });
  dlg.oncancel = (e) => e.preventDefault();
  $('#setupForm').onsubmit = async (e) => { e.preventDefault();
    const scenarios = boxes.filter((x) => x.checked).map((x) => { const s = dlg.querySelector(`select[data-for=${x.value}]`); return scenBody(x.value, s ? s.value : undefined); });
    if (await post('/api/run/start', { seed: $('#seedIn').value.trim(), scenarios })) { dlg.close(); state = null; } };
  dlg.showModal();
}

/* ---------------------------------------------------------------- 3D scene */
const host = $('#three');
const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
host.appendChild(renderer.domElement);
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x1b1f23);
const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 2000);
const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true; controls.maxPolarAngle = Math.PI * 0.49;
scene.add(new THREE.AmbientLight(0xffffff, 0.75));
const sun = new THREE.DirectionalLight(0xffffff, 0.8); sun.position.set(40, 80, 30); scene.add(sun);
let focus = null, home = null, lat0 = 0, lon0 = 0, KX = 1;
const KZ = 110.574;
const proj = (lat, lon) => new THREE.Vector3((lon - lon0) * KX, 0, -(lat - lat0) * KZ);
const potGroup = new THREE.Group(), truthGroup = new THREE.Group(), truckGroup = new THREE.Group();
scene.add(potGroup, truthGroup, truckGroup);
let potKey = '', truthKey = '';
const raycaster = new THREE.Raycaster(), ndc = new THREE.Vector2();

function resize() {
  const w = host.clientWidth, h = host.clientHeight;
  renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
}
addEventListener('resize', resize);

function buildScene() {
  const segs = cfg.segments;
  lat0 = segs.reduce((a, s) => a + s.start[0] + s.end[0], 0) / (2 * segs.length);
  lon0 = segs.reduce((a, s) => a + s.start[1] + s.end[1], 0) / (2 * segs.length);
  KX = 111.32 * Math.cos(lat0 * Math.PI / 180);
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(600, 600), new THREE.MeshStandardMaterial({ color: 0x20262b, roughness: 1 }));
  ground.rotation.x = -Math.PI / 2; scene.add(ground);
  const grid = new THREE.GridHelper(600, 120, 0x2d353c, 0x262d33); grid.position.y = 0.01; scene.add(grid);
  const jointMat = new THREE.MeshStandardMaterial({ color: 0x59636c, roughness: .9 });
  const pts = [];
  segs.forEach((s) => {
    const a = proj(...s.start), b = proj(...s.end), d = b.clone().sub(a), len = d.length();
    pts.push(a, b);
    const mat = new THREE.MeshStandardMaterial({ color: NEUTRAL, roughness: .9, emissive: 0x000000 });
    const m = new THREE.Mesh(new THREE.BoxGeometry(ROAD_W, 0.12, len), mat);
    m.position.copy(a.clone().add(b).multiplyScalar(.5)); m.position.y = .06; m.rotation.y = Math.atan2(d.x, d.z);
    m.userData.id = s.id; scene.add(m); segMesh.push(m);
    const line = new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.01, len), new THREE.MeshBasicMaterial({ color: 0xcfd6dc, transparent: true, opacity: .45 }));
    line.position.copy(m.position); line.position.y = .125; line.rotation.y = m.rotation.y; scene.add(line);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: 0x6fb3d9 }));
    edges.scale.set(1.12, 1.6, 1.0); edges.visible = false; m.add(edges); m.userData.edges = edges;
    const mid = a.clone().add(b).multiplyScalar(.5); segMid.push(mid); segDir.push(d.clone().normalize());
    const mast = new THREE.Mesh(new THREE.CylinderGeometry(.04, .04, .8), jointMat);
    const n = new THREE.Vector3(-d.z, 0, d.x).normalize().multiplyScalar(ROAD_W * .75);
    mast.position.copy(mid).add(n); mast.position.y = .4; scene.add(mast);
    const lbl = document.createElement('div'); lbl.className = 'lbl'; lbl.textContent = sid(s.id); $('#labels').appendChild(lbl); s._lbl = lbl;
  });
  [segs[0].start, ...segs.map((s) => s.end)].forEach((p) => {
    const j = new THREE.Mesh(new THREE.CylinderGeometry(ROAD_W / 2, ROAD_W / 2, .09, 24), jointMat);
    const v = proj(...p); j.position.set(v.x, .045, v.z); scene.add(j);
  });
  const box = new THREE.Box3().setFromPoints(pts), c = box.getCenter(new THREE.Vector3());
  const radius = box.getSize(new THREE.Vector3()).length() / 2;
  const dist = radius / Math.sin(THREE.MathUtils.degToRad(camera.fov / 2)) * 0.95;
  const elev = THREE.MathUtils.degToRad(50);
  home = { target: c.clone(), pos: c.clone().add(new THREE.Vector3(0, Math.sin(elev), Math.cos(elev)).multiplyScalar(dist)) };
  controls.target.copy(home.target); camera.position.copy(home.pos);
  renderer.domElement.addEventListener('click', onClick);
  resize();
}

function onClick(ev) {
  const r = renderer.domElement.getBoundingClientRect();
  ndc.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  raycaster.setFromCamera(ndc, camera);
  const hit = raycaster.intersectObjects(segMesh, false)[0];
  if (hit) select(hit.object.userData.id, true);
}

function select(i, fly) {
  selected = i;
  segMesh.forEach((m, k) => { m.userData.edges.visible = k === i; });
  if (fly) focus = { target: segMid[i].clone(), pos: segMid[i].clone().add(new THREE.Vector3(0, 9, 11)) };
  renderList(); renderDetail(); setTab('detail');
  loadHistory();
}

function updateScene(t) {
  if (!state || !state.segments) return;
  state.segments.forEach((s, i) => {
    const m = segMesh[i];
    const col = layer === 'cond' ? condColor(s.ci) : statusColor(s.status);
    m.material.color.lerp(col, 0.35);
    const pulse = !reduced && (layer === 'traf' ? s.status === 'red' : s.ci < 45);
    m.material.emissive.copy(col).multiplyScalar(pulse ? 0.18 + 0.14 * Math.sin(t * 0.003) : 0);
    cfg.segments[i]._lbl.className = 'lbl' + (s.status === 'red' ? ' abn-red' : s.status === 'amber' ? ' abn-amber' : '');
  });
  const potKeyNow = JSON.stringify(state.segments.map((s) => s.potholes.map((p) => p.id)));
  if (potKeyNow !== potKey) {
    potKey = potKeyNow; potGroup.clear();
    state.segments.forEach((s) => s.potholes.forEach((p) => {
      const cone = new THREE.Mesh(new THREE.ConeGeometry(.16, .6, 10), new THREE.MeshStandardMaterial({ color: RED, emissive: 0x5a1a14 }));
      const v = proj(p.lat, p.lon); cone.position.set(v.x, .45, v.z); cone.rotation.x = Math.PI; potGroup.add(cone);
    }));
  }
  const tk = showTruth && state.truth ? JSON.stringify(state.truth.potholes) : '';
  if (tk !== truthKey) {
    truthKey = tk; truthGroup.clear();
    if (tk) state.truth.potholes.forEach((arr, i) => arr.forEach((off) => {
      const sg = cfg.segments[i], f = Math.min(1, off / (sg.length_km * 1000));
      const lat = sg.start[0] + f * (sg.end[0] - sg.start[0]), lon = sg.start[1] + f * (sg.end[1] - sg.start[1]);
      const ring = new THREE.Mesh(new THREE.TorusGeometry(.26, .03, 8, 24), new THREE.MeshBasicMaterial({ color: 0xffffff }));
      const v = proj(lat, lon); ring.position.set(v.x, .2, v.z); ring.rotation.x = Math.PI / 2; truthGroup.add(ring);
    }));
  }
  const seen = new Set();
  state.fleet.forEach((f) => {
    seen.add(f.vehicle_id);
    let m = trucks.get(f.vehicle_id);
    if (!m) {
      m = new THREE.Mesh(new THREE.BoxGeometry(.26, .22, .55), new THREE.MeshStandardMaterial({ color: 0xaab4bd }));
      m.userData.target = new THREE.Vector3(); truckGroup.add(m); trucks.set(f.vehicle_id, m);
      const v0 = proj(f.lat, f.lon); m.position.set(v0.x, .25, v0.z);
    }
    const d = segDir[f.segment_id], v = proj(f.lat, f.lon);
    const lane = new THREE.Vector3(-d.z, 0, d.x).multiplyScalar((f.direction === 0 ? 1 : -1) * ROAD_W * .22);
    m.userData.target.copy(v).add(lane); m.userData.target.y = .25;
    m.rotation.y = Math.atan2(d.x, d.z) + (f.direction === 0 ? 0 : Math.PI);
    m.material.color.set((f.gvw_t || 0) > 40 ? 0xe3a72f : 0xaab4bd);
  });
  trucks.forEach((m, id) => { if (!seen.has(id)) { truckGroup.remove(m); trucks.delete(id); } else m.position.lerp(m.userData.target, 0.18); });
}

const tmp = new THREE.Vector3();
function animate(t) {
  requestAnimationFrame(animate);
  if (focus) {
    controls.target.lerp(focus.target, 0.08); camera.position.lerp(focus.pos, 0.08);
    if (camera.position.distanceTo(focus.pos) < 0.2) focus = null;
  }
  controls.update(); updateScene(t);
  const w = host.clientWidth, h = host.clientHeight;
  cfg && cfg.segments.forEach((s, i) => {
    tmp.copy(segMid[i]); tmp.y = .5; tmp.project(camera);
    const vis = tmp.z < 1 && Math.abs(tmp.x) < 1.05 && Math.abs(tmp.y) < 1.05;
    s._lbl.style.display = vis ? '' : 'none';
    s._lbl.style.left = ((tmp.x * .5 + .5) * w) + 'px'; s._lbl.style.top = ((-tmp.y * .5 + .5) * h) + 'px';
  });
  renderer.render(scene, camera);
}

/* ---------------------------------------------------------------- panels */
function renderList() {
  if (!state || !state.segments) return;
  const box = $('#segList');
  if (box.children.length !== state.segments.length) {
    box.innerHTML = state.segments.map((s) => `<button class="segrow" data-id="${s.id}" title="${s.name}">
      <span class="id">${sid(s.id)}</span><span class="bar-track"><span class="bar-fill" style="display:block"></span></span>
      <span class="v"></span></button>`).join('');
  }
  state.segments.forEach((s, i) => {
    const r = box.children[i], fill = r.querySelector('.bar-fill'), v = r.querySelector('.v');
    const vmin = Math.min(...s.speed.filter((x) => x !== null), 999);
    const sp = vmin === 999 ? null : Math.round(vmin);
    const c = layer === 'cond' ? cls(s.ci) : (s.status === 'red' ? 'red' : s.status === 'amber' ? 'amber' : '');
    r.classList.toggle('sel', s.id === selected);
    fill.className = 'bar-fill' + (layer === 'cond' && c ? ' ' + c : '');
    fill.style.width = (layer === 'cond' ? Math.round(s.ci) : Math.min(100, sp || 0)) + '%';
    v.className = 'v' + (c ? ' ' + c : '');
    v.textContent = layer === 'cond' ? Math.round(s.ci) : (sp === null ? '-' : sp);
  });
}

function renderKpis() {
  const k = state.kpi;
  const cells = [['Active alarms', k.active, false], ['Unacknowledged', k.unacknowledged, k.unacknowledged > 10],
    ['Raised, last 10 min', k.rate_per_10min, k.flood_now], ['Flood events', k.flood_events, k.flood_events > 0]];
  setHtml($('#kpis'), cells.map(([l, v, a]) => `<div class="kpi ${a ? 'abn' : ''}"><b>${v}</b><span>${l}</span></div>`).join(''));
}

function renderAlarms() {
  const al = state.alarms;
  const head = al.length ? `<div class="btnrow"><button id="ackAll">Acknowledge all</button></div>` : '';
  setHtml($('#tab-alarms'), head + (al.slice(0, 60).map((a) => `
    <div class="alarm ${a.priority} ${a.state === 'rtn_unack' ? 'rtn' : ''}">
      <div class="t"><span>${a.tag}</span><span>${a.priority}</span></div>
      <div>${a.message}</div>
      <div class="m">${a.raised_value !== null && a.raised_value !== undefined ? 'Raised at ' + fmt(a.raised_value, 1) + ' | ' : ''}${a.setpoint}${a.lat ? ' | ' + a.lat.toFixed(4) + ', ' + a.lon.toFixed(4) : ''}</div>
      <div class="a">Action: ${a.action}</div>
      <div class="m">${a.state === 'rtn_unack' ? 'Returned to normal, not acknowledged' : a.state === 'active_ack' ? 'Acknowledged' : 'Active, not acknowledged'}
        ${a.state !== 'active_ack' ? `<button data-ack="${a.id}">Acknowledge</button>` : ''}</div>
    </div>`).join('') || '<div class="empty">No active alarms.</div>'));
}

function renderAdvisories() {
  setHtml($('#tab-advisories'), state.advisories.map((a) => `
    <div class="adv"><b>${sid(a.segment_id)}</b> ${a.kind === 'bypass' ? 'reroute' : 'hold'} advice, +${Math.round(a.delay_min / 5) * 5} min<div class="note">${a.text}</div></div>`).join('')
    || '<div class="empty">No segment currently warrants a reroute or hold advisory.</div>');
}

function renderMaint() {
  const rows = state.maintenance.slice(0, 10).map((m) => `<tr>
    <td>${sid(m.segment_id)}</td><td class="num">${Math.round(m.ci)}</td>
    <td class="num">${m.rul_days === null ? '-' : Math.round(m.rul_days / 5) * 5}</td><td class="num">${m.potholes}</td>
    <td class="act-${m.action}">${m.action}</td>
    <td>${m.action === 'monitor' ? '' : `<button data-wo="${m.segment_id}:${m.action}">Order</button>`}</td></tr>`).join('');
  setHtml($('#tab-maint'), `<table><thead><tr><th>Seg</th><th class="num">CI</th><th class="num">RUL d</th><th class="num">Pot.</th><th>Action</th><th></th></tr></thead><tbody>${rows}</tbody></table>
    <p class="note">Ranked by condition, confirmed potholes and remaining life (days, rounded to 5). Relative cost: patch 1, resurface 12.</p>`);
}

let detailFor = -1;
function renderDetail() {
  if (!state || !state.segments) return;
  const s = state.segments[selected];
  if (detailFor !== selected || !$('#dRows')) {
    detailFor = selected;
    $('#tab-detail').innerHTML = `<h2 id="dTitle"></h2><div id="dRows"></div>
      <div class="btnrow"><button id="woPatch">Order patching</button><button id="woRes">Order resurfacing</button></div>
      <canvas id="chart" class="chart" width="700" height="300"></canvas>
      <p class="note" id="dNote"></p>`;
    $('#dRows')._h = ''; hist = null;
  }
  const row = (l, v) => `<div class="row"><span>${l}</span><span>${v}</span></div>`;
  const inc = s.incident ? `${s.incident.kind} (severity ${fmt(s.incident.severity, 2)})` : 'none';
  $('#dTitle').textContent = s.name;
  setHtml($('#dRows'), `
    ${row('Condition index (estimated)', `${fmt(s.ci, 1)} ± ${fmt(s.ci_sd, 1)}`)}
    ${row('Roughness IRI (estimated)', fmt(s.iri, 1) + ' m/km')}
    ${row('Remaining life to CI 45', s.rul_days === null ? 'not yet estimated' : fmt(s.rul_days, 0) + ' days')}
    ${row('Load-response multiplier', `${fmt(s.theta, 2)} ± ${fmt(s.theta_sd, 2)}`)}
    ${row('Speed outbound / inbound', `${fmt(s.speed[0], 0)} / ${fmt(s.speed[1], 0)} km/h`)}
    ${row('Flow per direction, outbound / inbound', `${fmt(s.flow_vph[0], 0)} / ${fmt(s.flow_vph[1], 0)} veh/h`)}
    ${row('ESAL per truck (WIM)', fmt(s.esal_per_truck, 2))}
    ${row('Pavement temperature', fmt(s.pav_temp, 1) + ' °C')}
    ${row('Confirmed potholes', s.potholes.length ? s.potholes.map((p) => `${p.lat.toFixed(4)}, ${p.lon.toFixed(4)}`).join('<br>') : 'none')}
    ${row('Incident', inc)}
    ${row('Station data', s.stale ? 'stale' : 'current')}
    ${row('Roughness observations absorbed', s.probe_updates)}`);
  $('#dNote').textContent = 'Condition index over time: estimate with one standard deviation band' + (showTruth ? ', and simulator ground truth (white).' : '.');
  drawChart();
}

let hist = null;
async function loadHistory() {
  if (!state || !state.segments) return;
  try { hist = await (await fetch(`/api/segment/${selected}/history`)).json(); drawChart(); } catch (e) {}
}
function drawChart() {
  const c = $('#chart'); if (!c || !hist || !hist.twin.length) return;
  const g = c.getContext('2d'), W = c.width, H = c.height; g.clearRect(0, 0, W, H);
  const t0 = hist.twin[0].ts, t1 = Math.max(hist.twin[hist.twin.length - 1].ts, t0 + 86400);
  const x = (t) => 30 + (W - 40) * (t - t0) / (t1 - t0), y = (v) => H - 20 - (H - 35) * v / 100;
  g.strokeStyle = '#39414a'; g.fillStyle = '#8e99a4'; g.font = '16px system-ui';
  [0, 45, 100].forEach((v) => { g.beginPath(); g.moveTo(30, y(v)); g.lineTo(W - 10, y(v)); g.stroke(); g.fillText(v, 2, y(v) + 5); });
  g.fillStyle = 'rgba(111,179,217,.22)'; g.beginPath();
  hist.twin.forEach((p, i) => { i ? g.lineTo(x(p.ts), y(p.ci + p.sd)) : g.moveTo(x(p.ts), y(p.ci + p.sd)); });
  for (let i = hist.twin.length - 1; i >= 0; i--) g.lineTo(x(hist.twin[i].ts), y(hist.twin[i].ci - hist.twin[i].sd));
  g.fill();
  const line = (arr, col) => { g.strokeStyle = col; g.lineWidth = 2; g.beginPath(); arr.forEach((p, i) => { i ? g.lineTo(x(p.ts), y(p.ci)) : g.moveTo(x(p.ts), y(p.ci)); }); g.stroke(); };
  line(hist.twin, '#6fb3d9');
  if (showTruth && hist.truth.length) line(hist.truth, '#ffffff');
  g.fillStyle = '#8e99a4'; g.fillText('days', W - 48, H - 4);
}

function setTab(n) {
  document.querySelectorAll('.tab').forEach((b) => b.classList.toggle('on', b.dataset.tab === n));
  document.querySelectorAll('.pane').forEach((p) => { p.hidden = p.id !== 'tab-' + n; });
}

function renderKey() {
  const sw = (c, t) => `<div><i style="background:${c}"></i>${t}</div>`;
  $('#key').innerHTML = layer === 'cond'
    ? sw('#7d8892', 'Condition index 65 or higher') + sw('#e3a72f', 'Declining (45 to 65)') + sw('#e0483a', 'Critical (below 45)') + sw('#e0483a', 'Red pin: confirmed pothole') + sw('#aab4bd', 'Truck (amber when over 40 t)')
    : sw('#7d8892', 'Flowing') + sw('#e3a72f', 'Below 30 km/h') + sw('#e0483a', 'Below 10 km/h or closed') + sw('#474f57', 'No current station data');
}

function render() {
  if (!state) return;
  if (state.stopped) { $('#runbar').textContent = 'No simulation running'; $('#btnStop').hidden = true; openSetup(); return; }
  if (!state.segments) return;
  if ($('#btnStop').hidden && cfg.runs) $('#btnStop').hidden = false;
  $('#clock').textContent = `Day ${Math.floor(state.clock.day) + 1}, ${String(Math.floor(state.clock.hour)).padStart(2, '0')}:${String(Math.floor((state.clock.hour % 1) * 60)).padStart(2, '0')}` +
    (state.weather.rain_mm_h > 0.1 ? `  |  rain ${fmt(state.weather.rain_mm_h, 1)} mm/h` : '') + (state.weather.air_temp_c ? `  |  ${fmt(state.weather.air_temp_c, 0)} °C` : '');
  $('#btnPause').textContent = state.control.paused ? 'Run' : 'Pause';
  if (document.activeElement !== $('#speed')) $('#speed').value = String(state.control.speed);
  renderRunbar(); renderScenMenu(); renderKpis(); renderList(); renderAlarms(); renderAdvisories(); renderMaint();
  if (!document.querySelector('#tab-detail').hidden) renderDetail();
}

/* ---------------------------------------------------------------- wiring */
document.querySelectorAll('.tab').forEach((b) => b.onclick = () => { setTab(b.dataset.tab); if (b.dataset.tab === 'detail') { renderDetail(); loadHistory(); } });

/* Dynamic panels re-render as data arrives, so actions are delegated: pointerdown fires before a re-render can
   detach the button; click handles keyboard activation (suppressed right after a pointerdown). */
let suppressClick = 0;
function act(t) {
  if (t.classList.contains('segrow')) select(+t.dataset.id, true);
  else if (t.dataset.ack) post(`/api/alarms/${t.dataset.ack}/ack`);
  else if (t.id === 'ackAll') post('/api/alarms/ack_all');
  else if (t.dataset.wo) { const [s, a] = t.dataset.wo.split(':'); post('/api/workorder', { segment_id: +s, action: a }); }
  else if (t.id === 'woPatch') post('/api/workorder', { segment_id: selected, action: 'patch' });
  else if (t.id === 'woRes') post('/api/workorder', { segment_id: selected, action: 'resurface' });
}
const dyn = (e) => { const t = e.target.closest && e.target.closest('button'); return t && (t.classList.contains('segrow') || t.dataset.ack || t.dataset.wo || ['ackAll', 'woPatch', 'woRes'].includes(t.id)) ? t : null; };
document.addEventListener('pointerdown', (e) => { const t = dyn(e); if (t && e.button === 0) { suppressClick = performance.now(); act(t); } });
document.addEventListener('click', (e) => { const t = dyn(e); if (t && performance.now() - suppressClick > 500) act(t); });
$('#layerCond').onclick = () => { layer = 'cond'; $('#layerCond').classList.add('on'); $('#layerTraf').classList.remove('on'); renderKey(); renderList(); };
$('#layerTraf').onclick = () => { layer = 'traf'; $('#layerTraf').classList.add('on'); $('#layerCond').classList.remove('on'); renderKey(); renderList(); };
$('#resetView').onclick = () => { focus = { target: home.target.clone(), pos: home.pos.clone() }; };
$('#truthToggle').onchange = (e) => { showTruth = e.target.checked; renderDetail(); };
$('#token').oninput = (e) => { token = e.target.value; };
$('#btnPause').onclick = () => post('/api/control', { paused: !state.control.paused });
$('#btnStop').onclick = () => { if (confirm('Stop this simulation and discard its state? You can start a new one afterwards.')) post('/api/run/stop'); };
$('#scenBody').addEventListener('click', (e) => { const b = e.target.closest('.scen-item'); if (!b || b.disabled) return; $('#scenMenu').open = false; post('/api/scenario', scenBody(b.dataset.kind, selected)); });
$('#speed').onchange = (e) => post('/api/control', { speed: +e.target.value });
setInterval(() => { if (!$('#tab-detail').hidden) loadHistory(); }, 5000);

function connect() {
  const ws = new WebSocket((location.protocol === 'https:' ? 'wss' : 'ws') + '://' + location.host + '/ws');
  ws.onmessage = (e) => { state = JSON.parse(e.data); render(); };
  ws.onclose = () => setTimeout(connect, 2000);
}

(async function init() {
  cfg = await (await fetch('/api/config')).json();
  const mb = $('#modeBadge'); mb.textContent = cfg.mode.toUpperCase(); mb.className = 'badge ' + cfg.mode;
  if (cfg.mode !== 'simulation') $('#tokenBox').hidden = false;
  if (cfg.has_truth) $('#truthRow').hidden = false;
  if (cfg.mode === 'live') { $('#btnPause').hidden = true; $('#speed').hidden = true; }
  const mx = cfg.max_speed || 720; document.querySelectorAll('#speed option').forEach((o) => { o.disabled = +o.value > mx; });
  renderKey(); buildScene(); select(0, false); setTab('alarms');
  requestAnimationFrame(animate); connect();
})();
