"use strict";

const AGENT_META = {
  scout:      { name: "Scout",      role: "Analista de Mercados", emoji: "🔍" },
  content:    { name: "Content",    role: "Director de Riesgo",   emoji: "⚖️" },
  affiliate:  { name: "Affiliate",  role: "Conexiones",           emoji: "🔗" },
  trading:    { name: "Trading",    role: "Mesa de Operaciones",  emoji: "📈" },
  freelancer: { name: "Freelancer", role: "Desarrollo",           emoji: "💼" },
  social:     { name: "Social",     role: "Comunicaciones",       emoji: "📱" },
  analytics:  { name: "Analytics",  role: "Director de Estrategias", emoji: "📊" },
};
const AGENT_IDS = Object.keys(AGENT_META);
const DESK_POS = {
  scout: [-7.5, -3.2], analytics: [-2.5, -3.2], trading: [2.5, -3.2],
  content: [7.5, -3.2], freelancer: [-5, 2.6], social: [0, 2.6],
  affiliate: [5, 2.6],
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x050505);

const camera = new THREE.PerspectiveCamera(
  45, window.innerWidth / window.innerHeight, 0.1, 200);

const renderer = new THREE.WebGLRenderer({ antialias: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
document.getElementById("scene").appendChild(renderer.domElement);

scene.add(new THREE.AmbientLight(0xffffff, 0.55));
const dirLight = new THREE.DirectionalLight(0xffffff, 0.65);
dirLight.position.set(8, 14, 6);
scene.add(dirLight);

const floor = new THREE.Mesh(
  new THREE.BoxGeometry(22, 0.2, 14),
  new THREE.MeshPhongMaterial({ color: 0x111111 }));
floor.position.y = -0.1;
scene.add(floor);
const floorGrid = new THREE.GridHelper(21.8, 28, 0x2a2a2a, 0x1c1c1c);
floorGrid.position.y = 0.01;
scene.add(floorGrid);

function makeLabel(lines) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 140;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(0, 0, 0, 0.85)";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(0, 0, 512, 140, 18) : ctx.rect(0, 0, 512, 140);
  ctx.fill();
  ctx.strokeStyle = "#444444";
  ctx.lineWidth = 3;
  ctx.stroke();
  ctx.textAlign = "center";
  ctx.fillStyle = "#e8e8e8";
  ctx.font = "bold 44px Consolas";
  ctx.fillText(lines[0], 256, 58);
  ctx.fillStyle = "#f5c518";
  ctx.font = "30px Consolas";
  ctx.fillText(lines[1], 256, 106);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
  sp.scale.set(3.4, 0.93, 1);
  return sp;
}

const desks = {};

function buildDesk(id) {
  const meta = AGENT_META[id];
  const [x, z] = DESK_POS[id];
  const g = new THREE.Group();

  const table = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 0.14, 1.3),
    new THREE.MeshPhongMaterial({ color: 0x141414 }));
  table.position.y = 1.0;
  g.add(table);

  const leg = new THREE.Mesh(
    new THREE.BoxGeometry(2.3, 0.95, 0.15),
    new THREE.MeshPhongMaterial({ color: 0x0d0d0d }));
  leg.position.y = 0.5;
  g.add(leg);

  const monitorCanvas = document.createElement("canvas");
  monitorCanvas.width = 512; monitorCanvas.height = 256;
  const monitorCtx = monitorCanvas.getContext("2d");
  const monitorTex = new THREE.CanvasTexture(monitorCanvas);
  const monitor = new THREE.Mesh(
    new THREE.BoxGeometry(1.3, 0.75, 0.07),
    new THREE.MeshPhongMaterial({ color: 0x0a0a0a }));
  monitor.position.set(0, 1.6, -0.35);
  g.add(monitor);
  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(1.2, 0.65),
    new THREE.MeshBasicMaterial({ map: monitorTex }));
  screen.position.set(0, 1.6, -0.31);
  g.add(screen);

  const avatar = new THREE.Mesh(
    new THREE.SphereGeometry(0.34, 20, 20),
    new THREE.MeshPhongMaterial({ color: 0x38bdf8, emissive: 0x38bdf8,
      emissiveIntensity: 0.3 }));
  avatar.position.set(0, 1.05, 0.85);
  g.add(avatar);

  const chair = new THREE.Mesh(
    new THREE.CylinderGeometry(0.32, 0.32, 0.12, 16),
    new THREE.MeshPhongMaterial({ color: 0x111111 }));
  chair.position.set(0, 0.6, 0.85);
  g.add(chair);

  const label = makeLabel([meta.emoji + " " + meta.name, meta.role]);
  label.position.set(0, 2.6, 0);
  g.add(label);

  const light = new THREE.PointLight(0x38bdf8, 0.5, 7);
  light.position.set(0, 2.2, 0);
  g.add(light);

  g.position.set(x, 0.1, z);
  g.traverse(o => { o.userData.agentId = id; });
  scene.add(g);
  desks[id] = { group: g, light, avatar, monitor, monitorCanvas, monitorCtx,
                monitorTex, label, working: false };
}

AGENT_IDS.forEach(buildDesk);

const ceoTable = new THREE.Mesh(
  new THREE.BoxGeometry(4.4, 0.18, 1.7),
  new THREE.MeshPhongMaterial({ color: 0x141414 }));
ceoTable.position.set(0, 1.0, -6);
scene.add(ceoTable);
const ceoLeg = new THREE.Mesh(
  new THREE.BoxGeometry(4.0, 0.95, 0.2),
  new THREE.MeshPhongMaterial({ color: 0x0d0d0d }));
ceoLeg.position.set(0, 0.5, -6);
scene.add(ceoLeg);
const ceoLabel = makeLabel(["🧑‍💼 CEO", "Mesa de Carlos"]);
ceoLabel.position.set(0, 2.7, -6);
scene.add(ceoLabel);

const boardCanvas = document.createElement("canvas");
boardCanvas.width = 1024; boardCanvas.height = 512;
const boardCtx = boardCanvas.getContext("2d");
const boardTex = new THREE.CanvasTexture(boardCanvas);
const whiteboard = new THREE.Mesh(
  new THREE.PlaneGeometry(7.5, 3.4),
  new THREE.MeshBasicMaterial({ map: boardTex }));
whiteboard.position.set(0, 3.0, -6.85);
scene.add(whiteboard);

const CAM = { theta: Math.PI / 4, phi: 1.0, radius: 19 };
function updateCamera() {
  camera.position.set(
    CAM.radius * Math.sin(CAM.phi) * Math.cos(CAM.theta),
    CAM.radius * Math.cos(CAM.phi),
    CAM.radius * Math.sin(CAM.phi) * Math.sin(CAM.theta));
  camera.lookAt(0, 1.2, 0);
}
updateCamera();

let dragging = false, dragMoved = 0, lastX = 0, lastY = 0;
renderer.domElement.addEventListener("pointerdown", e => {
  dragging = true; dragMoved = 0; lastX = e.clientX; lastY = e.clientY;
});
window.addEventListener("pointerup", () => { dragging = false; });
window.addEventListener("pointermove", e => {
  if (!dragging) return;
  const dx = e.clientX - lastX, dy = e.clientY - lastY;
  dragMoved += Math.abs(dx) + Math.abs(dy);
  lastX = e.clientX; lastY = e.clientY;
  CAM.theta += dx * 0.005;
  CAM.phi = Math.min(1.35, Math.max(0.45, CAM.phi - dy * 0.005));
  updateCamera();
});
renderer.domElement.addEventListener("wheel", e => {
  CAM.radius = Math.min(30, Math.max(10, CAM.radius + e.deltaY * 0.02));
  updateCamera();
}, { passive: true });

function wrapText(ctx, text, x, y, maxW, lh, maxLines) {
  const words = String(text || "").split(/\s+/);
  let line = "", lines = 0;
  for (let i = 0; i < words.length; i++) {
    const test = line ? line + " " + words[i] : words[i];
    if (ctx.measureText(test).width > maxW && line) {
      ctx.fillText(line, x, y + lines * lh);
      lines++;
      if (lines >= maxLines - 1) {
        ctx.fillText(line + " …", x, y + lines * lh);
        return lines + 1;
      }
      line = words[i];
    } else {
      line = test;
    }
  }
  if (line) { ctx.fillText(line, x, y + lines * lh); lines++; }
  return lines;
}

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

const clock = new THREE.Clock();

function animate() {
  requestAnimationFrame(animate);
  const t = clock.getElapsedTime();
  let i = 0;
  for (const id of AGENT_IDS) {
    const d = desks[id];
    if (d.working) {
      d.avatar.position.y = 1.05 + Math.sin(t * 6 + i) * 0.13;
    } else {
      d.avatar.position.y = 1.05;
    }
    i++;
  }
  renderer.render(scene, camera);
}
animate();


let state = null;

function drawMonitor(id, text, working) {
  const d = desks[id];
  if (!d) return;
  const ctx = d.monitorCtx;
  ctx.fillStyle = working ? "#1a1200" : "#001a00";
  ctx.fillRect(0, 0, 512, 256);
  ctx.fillStyle = working ? "#f5c518" : "#4dff88";
  ctx.font = "bold 34px Consolas";
  ctx.textAlign = "center";
  wrapText(ctx, text || "—", 256, 70, 460, 44, 4);
  d.monitorTex.needsUpdate = true;
}

function applyState() {
  if (!state) return;
  for (const a of state.agents) {
    const d = desks[a.id];
    if (!d) continue;
    const working = a.status === "working" || localWorking.has(a.id);
    d.working = working;
    d.light.color.setHex(working ? 0xf5c518 : 0x38bdf8);
    d.light.intensity = working ? 1.8 : 0.5;
    const avColor = working ? 0xf5c518 : 0x38bdf8;
    d.avatar.material.color.setHex(avColor);
    d.avatar.material.emissive.setHex(avColor);
    const taskText = a.task && a.task.title ? a.task.title : "en espera";
    drawMonitor(a.id, taskText, working);
  }
  updateHUD();
  renderFeed();
  drawBoard();
  updateBubbles(Date.now());
  updateLine(Date.now());
}

const localWorking = new Set();
let pollInFlight = false;

async function poll() {
  if (pollInFlight) return;
  pollInFlight = true;
  try {
    const r = await fetch("/api/fund/office");
    if (!r.ok) throw new Error("HTTP " + r.status);
    state = await r.json();
    document.getElementById("offline").classList.add("hidden");
  } catch (e) {
    document.getElementById("offline").classList.remove("hidden");
  } finally {
    pollInFlight = false;
  }
  try {
    applyState();
  } catch (e) {
    console.error("render error en applyState:", e);
  }
}
setInterval(poll, 3000);
poll();


const TICKER_SYMS = ["BTC", "ETH", "DIA", "TSLA", "USDJPY"];
const sessionBase = {};

function updateHUD() {
  if (!state) return;
  const f = state.fund;
  document.getElementById("hud-equity").textContent =
    "Equity $" + f.equity.toFixed(2) + " · PnL día $" + f.daily_pnl.toFixed(2);
  document.getElementById("hud-dd").textContent =
    "Drawdown " + (f.drawdown * 100).toFixed(1) + "%";
  document.getElementById("hud-trades").textContent =
    "Trades " + f.trades + " · Win " + Math.round(f.win_rate * 100) + "%";
  document.getElementById("hud-phase").textContent =
    f.phase === "aggressive" ? "FASE AGRESIVA" : "FASE MODERADA";

  const parts = [];
  for (const sym of TICKER_SYMS) {
    const p = state.tickers[sym];
    if (p == null) { parts.push(sym + " —"); continue; }
    if (sessionBase[sym] == null) sessionBase[sym] = p;
    const pct = ((p - sessionBase[sym]) / sessionBase[sym]) * 100;
    const sign = pct >= 0 ? "+" : "";
    parts.push(sym + " $" + p.toFixed(2) + " (" + sign + pct.toFixed(2) + "%)");
  }
  document.getElementById("hud-ticker").textContent = parts.join("   ");
}

function feedName(id) {
  if (id === "user") return "CEO";
  return (AGENT_META[id] && AGENT_META[id].name) || id;
}

function renderFeed() {
  if (!state) return;
  const ul = document.getElementById("feed-list");
  ul.innerHTML = "";
  for (const m of state.messages) {
    const li = document.createElement("li");
    const time = String(m.created_at || "").slice(11, 16);
    const when = document.createElement("span");
    when.className = "time";
    when.textContent = time;
    const who = document.createElement("span");
    who.className = "who";
    who.textContent = feedName(m.from_agent) + " → " + feedName(m.to_agent);
    li.appendChild(when);
    li.appendChild(who);
    li.appendChild(document.createElement("br"));
    li.appendChild(document.createTextNode(
      String(m.content || "").slice(0, 140)));
    ul.appendChild(li);
  }
}

function drawBoard() {
  if (!state) return;
  const f = state.fund;
  boardCtx.fillStyle = "#001200";
  boardCtx.fillRect(0, 0, 1024, 512);
  boardCtx.strokeStyle = "#1a5c1a";
  boardCtx.lineWidth = 6;
  boardCtx.strokeRect(10, 10, 1004, 492);
  boardCtx.shadowColor = "#4dff88";
  boardCtx.shadowBlur = 10;
  boardCtx.fillStyle = "#baffd0";
  boardCtx.textAlign = "left";
  boardCtx.font = "bold 58px Consolas";
  boardCtx.fillText("SEGUNDO CEREBRO CAPITAL", 50, 90);
  boardCtx.shadowBlur = 6;
  boardCtx.fillStyle = "#4dff88";
  boardCtx.font = "46px Consolas";
  boardCtx.fillText("ESTRATEGIA: " + (f.strategy || "—"), 50, 180);
  boardCtx.fillText("FASE: " + (f.phase === "aggressive" ? "AGRESIVA" : "MODERADA"), 50, 260);
  boardCtx.fillText("META: $" + Number(f.target).toLocaleString("es-VE"), 50, 340);
  boardCtx.fillStyle = f.daily_stop_hit ? "#ff7043" : "#baffd0";
  boardCtx.fillText("DRAWDOWN: " + (f.drawdown * 100).toFixed(1) + "%", 50, 430);
  boardCtx.shadowBlur = 0;
  boardTex.needsUpdate = true;
}

setInterval(() => {
  document.getElementById("hud-clock").textContent =
    "NY " + new Date().toLocaleTimeString("es-VE",
      { timeZone: "America/New_York", hour12: false });
}, 1000);


let bubble = null;
let bubbleMsgId = 0;
let bubbleUntil = 0;

function makeBubble(text) {
  const c = document.createElement("canvas");
  c.width = 640; c.height = 320;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(10, 10, 10, 0.95)";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(0, 0, 640, 320, 28) : ctx.rect(0, 0, 640, 320);
  ctx.fill();
  ctx.strokeStyle = "#f5c518";
  ctx.lineWidth = 6;
  ctx.stroke();
  ctx.fillStyle = "#4dff88";
  ctx.font = "36px Consolas";
  ctx.textAlign = "center";
  const clipped = String(text || "").slice(0, 90);
  wrapText(ctx, clipped, 320, 80, 560, 46, 5);
  const tex = new THREE.CanvasTexture(c);
  const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true }));
  sp.scale.set(3.7, 1.85, 1);
  return sp;
}

function updateBubbles(now) {
  if (!state) return;
  const newest = state.messages.find(m =>
    AGENT_IDS.includes(m.from_agent) && m.content);
  if (newest && newest.id !== bubbleMsgId) {
    bubbleMsgId = newest.id;
    if (bubble) { scene.remove(bubble); bubble = null; }
    bubble = makeBubble(newest.content);
    const d = desks[newest.from_agent];
    bubble.position.set(d.group.position.x, 3.5, d.group.position.z + 1.7);
    scene.add(bubble);
    bubbleUntil = now + 6000;
  }
  if (bubble && now > bubbleUntil) {
    scene.remove(bubble);
    bubble = null;
  }
}

let lineMesh = null;
let lineTraveler = null;
let lineMsgId = 0;
const lineState = { from: null, to: null };

function updateLine(now) {
  if (!state) return;
  const m = state.messages.find(x =>
    AGENT_IDS.includes(x.from_agent) && AGENT_IDS.includes(x.to_agent) &&
    x.from_agent !== x.to_agent);
  if (!m) {
    if (lineMesh) { scene.remove(lineMesh); lineMesh = null; }
    if (lineTraveler) { scene.remove(lineTraveler); lineTraveler = null; }
    lineMsgId = 0;
    return;
  }
  if (m.id !== lineMsgId) {
    lineMsgId = m.id;
    if (lineMesh) { scene.remove(lineMesh); lineMesh = null; }
    if (lineTraveler) { scene.remove(lineTraveler); lineTraveler = null; }
    const a = desks[m.from_agent].group.position;
    const b = desks[m.to_agent].group.position;
    lineState.from = new THREE.Vector3(a.x, 2.2, a.z);
    lineState.to = new THREE.Vector3(b.x, 2.2, b.z);
    const geo = new THREE.BufferGeometry().setFromPoints(
      [lineState.from, lineState.to]);
    lineMesh = new THREE.Line(geo,
      new THREE.LineBasicMaterial({ color: 0x4dff88, transparent: true, opacity: 0.75 }));
    scene.add(lineMesh);
    lineTraveler = new THREE.Mesh(
      new THREE.SphereGeometry(0.14, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x4dff88 }));
    scene.add(lineTraveler);
  }
  if (lineMesh && lineTraveler && lineState.from) {
    const t = (now % 2000) / 2000;
    lineTraveler.position.lerpVectors(lineState.from, lineState.to, t);
  }
}


const chatPanel = document.getElementById("chat-panel");
const chatLog = document.getElementById("chat-log");
const chatInput = document.getElementById("chat-input");
const chatSend = document.getElementById("chat-send");
const chatStatus = document.getElementById("chat-status");
let currentChat = null;

function chatBubbleRow(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  chatLog.appendChild(div);
  chatLog.scrollTop = chatLog.scrollHeight;
  return div;
}

function openChat(id) {
  currentChat = id;
  const meta = AGENT_META[id];
  document.getElementById("chat-title").textContent =
    meta.emoji + " " + meta.name + " — " + meta.role;
  chatLog.innerHTML = "";
  chatStatus.textContent = "";
  chatStatus.className = "";
  if (state) {
    const hist = state.messages
      .filter(m => m.from_agent === id || m.to_agent === id)
      .slice(0, 10)
      .reverse();
    for (const m of hist) {
      const mine = m.to_agent === id && m.from_agent === "user";
      chatBubbleRow(mine ? "mine" : "theirs",
        (mine ? "Tú: " : feedName(m.from_agent) + ": ") + m.content);
    }
  }
  chatPanel.classList.remove("hidden");
  chatInput.focus();
}

document.getElementById("chat-close").addEventListener("click", () => {
  chatPanel.classList.add("hidden");
  currentChat = null;
});

async function sendChat(query) {
  const target = currentChat;
  chatSend.disabled = true;
  chatStatus.className = "busy";
  chatStatus.style.color = "#00e676";
  chatStatus.textContent = "Pensando… (hasta 60 s)";
  chatBubbleRow("mine", "Tú: " + query);
  localWorking.add(target);
  try {
    applyState();
  } catch (e) { /* render local del estado working */ }
  try {
    const r = await fetch("/api/chat/" + target, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query: query }),
    });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (currentChat === target) {
      chatBubbleRow("theirs", AGENT_META[target].name + ": " + d.response);
      chatStatus.textContent = "";
    }
  } catch (e) {
    if (currentChat === target) {
      chatStatus.style.color = "#f87171";
      chatStatus.textContent = "No se pudo enviar: " + e.message;
    }
  } finally {
    localWorking.delete(target);
    try {
      applyState();
    } catch (e) { /* render local */ }
    if (currentChat === target) {
      chatStatus.className = "";
      chatSend.disabled = false;
      chatInput.value = "";
      chatInput.focus();
    } else {
      chatSend.disabled = false;
    }
  }
}

document.getElementById("chat-form").addEventListener("submit", e => {
  e.preventDefault();
  const q = chatInput.value.trim();
  if (!q || chatSend.disabled || !currentChat) return;
  sendChat(q);
});

renderer.domElement.addEventListener("click", () => {
  if (dragMoved > 6) return;
  const ndc = new THREE.Vector2(
    (lastX / window.innerWidth) * 2 - 1,
    -(lastY / window.innerHeight) * 2 + 1);
  const ray = new THREE.Raycaster();
  ray.setFromCamera(ndc, camera);
  const hits = ray.intersectObjects(
    Object.values(desks).map(d => d.group), true);
  if (hits.length) {
    const id = hits[0].object.userData.agentId;
    if (id) openChat(id);
  }
});
