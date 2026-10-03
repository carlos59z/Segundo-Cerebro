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
const AGENT_COLORS = {
  scout: 0x38bdf8, content: 0xfbbf24, affiliate: 0xf87171, trading: 0x34d399,
  freelancer: 0xf472b6, social: 0x60a5fa, analytics: 0xa78bfa,
};
const DESK_POS = {
  scout: [-7.5, -3.2], analytics: [-2.5, -3.2], trading: [2.5, -3.2],
  content: [7.5, -3.2], freelancer: [-5, 2.6], social: [0, 2.6],
  affiliate: [5, 2.6],
};

const scene = new THREE.Scene();
scene.background = new THREE.Color(0x0b1220);

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
  new THREE.MeshPhongMaterial({ color: 0x1e293b }));
floor.position.y = -0.1;
scene.add(floor);

function makeLabel(lines) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 140;
  const ctx = c.getContext("2d");
  ctx.fillStyle = "rgba(2, 6, 23, 0.75)";
  ctx.beginPath();
  ctx.roundRect ? ctx.roundRect(0, 0, 512, 140, 18) : ctx.rect(0, 0, 512, 140);
  ctx.fill();
  ctx.textAlign = "center";
  ctx.fillStyle = "#e2e8f0";
  ctx.font = "bold 44px Segoe UI";
  ctx.fillText(lines[0], 256, 58);
  ctx.fillStyle = "#7dd3fc";
  ctx.font = "30px Segoe UI";
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
    new THREE.MeshPhongMaterial({ color: 0x334155 }));
  table.position.y = 1.0;
  g.add(table);

  const leg = new THREE.Mesh(
    new THREE.BoxGeometry(2.3, 0.95, 0.15),
    new THREE.MeshPhongMaterial({ color: 0x1f2937 }));
  leg.position.y = 0.5;
  g.add(leg);

  const monitorCanvas = document.createElement("canvas");
  monitorCanvas.width = 512; monitorCanvas.height = 256;
  const monitorCtx = monitorCanvas.getContext("2d");
  const monitorTex = new THREE.CanvasTexture(monitorCanvas);
  const monitor = new THREE.Mesh(
    new THREE.BoxGeometry(1.3, 0.75, 0.07),
    new THREE.MeshPhongMaterial({ color: 0x0f172a }));
  monitor.position.set(0, 1.6, -0.35);
  g.add(monitor);
  const screen = new THREE.Mesh(
    new THREE.PlaneGeometry(1.2, 0.65),
    new THREE.MeshBasicMaterial({ map: monitorTex }));
  screen.position.set(0, 1.6, -0.31);
  g.add(screen);

  const color = AGENT_COLORS[id];
  const avatar = new THREE.Mesh(
    new THREE.SphereGeometry(0.34, 20, 20),
    new THREE.MeshPhongMaterial({ color, emissive: color, emissiveIntensity: 0.3 }));
  avatar.position.set(0, 1.05, 0.85);
  g.add(avatar);

  const chair = new THREE.Mesh(
    new THREE.CylinderGeometry(0.32, 0.32, 0.12, 16),
    new THREE.MeshPhongMaterial({ color: 0x0f172a }));
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
  new THREE.MeshPhongMaterial({ color: 0x7c2d12 }));
ceoTable.position.set(0, 1.0, -6);
scene.add(ceoTable);
const ceoLeg = new THREE.Mesh(
  new THREE.BoxGeometry(4.0, 0.95, 0.2),
  new THREE.MeshPhongMaterial({ color: 0x431407 }));
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

function animate() {
  requestAnimationFrame(animate);
  renderer.render(scene, camera);
}
animate();
