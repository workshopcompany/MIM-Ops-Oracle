"""
Changelog (solver_updated.py integration):
  ★ wall_friction_k slider added (0.0~10.0, default 3.0)
  ★ flow_decay slider added (0.0~2.0, default 0.5)
  ★ Two parameters added to session_state initialization
  ★ Two parameters added to submit_simulation params dict
  ★ Two parameters added to submit_simulation data payload
"""

import streamlit as st
import os
import requests
import numpy as np
import tempfile
import json
import time
from datetime import datetime
import trimesh
import streamlit.components.v1 as components
import base64

# ═══════════════════════════════════════════════════════════
# PAGE CONFIG
# ═══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="MIM-Ops Pro v3.2",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.title("🔬 MIM-Ops Pro v3.2: Oracle Cloud Edition")
st.markdown("**Metal Injection Molding (MIM) Flow Simulation Platform**")

# ═══════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════

def _get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError, Exception):
        return default

ORACLE_API_URL = _get_secret("ORACLE_API_URL", "http://132.145.187.95:5000")
ORACLE_API_KEY = _get_secret("API_KEY", "default-key")
GEMINI_API_KEY = _get_secret("GEMINI_API_KEY", "")

MATERIAL_FILE = os.path.join(os.path.dirname(__file__), "material_property.txt")
if not os.path.exists(MATERIAL_FILE):
    MATERIAL_FILE = "material_property.txt"

# ═══════════════════════════════════════════════════════════
# SESSION STATE 초기화
# ═══════════════════════════════════════════════════════════

def init_session_state():
    defaults = {
        "mesh": None,
        "mesh_bounds": None,
        "material": "CATAMOLD-304L",
        "props": {},
        "gate_x": 0.0,
        "gate_y": 0.0,
        "gate_z": 0.0,
        "gate_dia": 2.0,
        "gate_shape": "circular",
        "gate_width": 3.0,
        "gate_height": 2.0,
        "temp": 230.0,
        "press": 70.0,
        "vel_mms": 80.0,
        "etime": 1.0,
        "job_id": None,
        "sim_status": "idle",
        "last_result": None,
        "gate_suggestions": [],
        "gate_ai_advice": "",
        # ★ 신규: solver wall friction + flow decay
        "wall_friction_k": 3.0,
        "flow_decay": 0.5,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_session_state()

# ═══════════════════════════════════════════════════════════
# RAM 예측 / 해상도 추천
# ═══════════════════════════════════════════════════════════

def estimate_ram_gb(mesh, res_mm: float) -> tuple[int, float]:
    bounds = mesh.bounds
    bb = bounds[1] - bounds[0]
    bb = np.maximum(bb, 1e-6)
    grid_nx = int(np.ceil(bb[0] / res_mm))
    grid_ny = int(np.ceil(bb[1] / res_mm))
    grid_nz = int(np.ceil(bb[2] / res_mm))
    est_voxels = max(int(grid_nx) * int(grid_ny) * int(grid_nz), 1)
    BYTES_PER_VOXEL = 210
    est_ram_gb_val = (est_voxels * BYTES_PER_VOXEL) / (1024 ** 3)
    return est_voxels, est_ram_gb_val


def render_ram_advisor(mesh):
    rows = []
    for res_test in [0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
        _, ram_test = estimate_ram_gb(mesh, res_test)
        if ram_test <= 12:
            status = "✅ Under 16GB (Safe)"
        elif ram_test <= 18:
            status = "🟡 16~24GB (Caution)"
        elif ram_test <= 22:
            status = "⚠️ Near 24GB"
        else:
            status = "❌ Over 24GB (Danger)"
        rows.append({"Resolution (mm)": res_test, "Est. RAM (GB)": f"{ram_test:.1f}", "Status": status})

    st.dataframe(rows, use_container_width=True, hide_index=True)

    rec_16, rec_24 = None, None
    for res_test in [0.02, 0.05, 0.08, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0]:
        _, r = estimate_ram_gb(mesh, res_test)
        if r <= 16 * 0.75 and rec_16 is None:
            rec_16 = res_test
        if r <= 24 * 0.75 and rec_24 is None:
            rec_24 = res_test

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if rec_16:
            if st.button(f"💡 Apply 16GB recommended: {rec_16:.1f}mm", use_container_width=True):
                st.session_state.mesh_res_mm = float(rec_16)
                st.rerun()
    with col_r2:
        if rec_24:
            if st.button(f"💡 Apply 24GB recommended: {rec_24:.1f}mm", use_container_width=True):
                st.session_state.mesh_res_mm = float(rec_24)
                st.rerun()


# ═══════════════════════════════════════════════════════════
# 재료 데이터베이스 함수들
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def load_material_db(filepath: str) -> dict:
    db = {}
    default_materials = {
        "CATAMOLD-304L": {"nu": 4.0e-3, "rho": 7900.0, "Tmelt": 185.0, "Tmold": 40.0, "press_mpa": 110.0, "vel_mms": 25.0},
        "WAXBASE-304L":  {"nu": 4.0e-3, "rho": 7900.0, "Tmelt": 170.0, "Tmold": 35.0, "press_mpa": 100.0, "vel_mms": 30.0},
        "PA66+GF30":     {"nu": 4.0e-4, "rho": 1300.0, "Tmelt": 285.0, "Tmold": 85.0, "press_mpa": 110.0, "vel_mms": 80.0},
        "PP":            {"nu": 2.0e-4, "rho": 910.0,  "Tmelt": 230.0, "Tmold": 40.0, "press_mpa": 70.0,  "vel_mms": 130.0},
    }
    if not os.path.exists(filepath):
        return default_materials
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) < 7:
                    continue
                name = parts[0].upper()
                try:
                    db[name] = {
                        "nu":        float(parts[1]),
                        "rho":       float(parts[2]),
                        "Tmelt":     float(parts[3]),
                        "Tmold":     float(parts[4]),
                        "press_mpa": float(parts[5]),
                        "vel_mms":   float(parts[6]),
                    }
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        st.warning(f"Material DB load error: {e}")
        return default_materials
    return db if db else default_materials


def get_material_properties(material_name: str) -> dict:
    db = load_material_db(MATERIAL_FILE)
    name_upper = material_name.upper().strip()
    if name_upper in db:
        return {**db[name_upper], "material": name_upper, "source": "Exact match"}
    candidates = [k for k in db if name_upper in k or k in name_upper]
    if candidates:
        best = candidates[0]
        return {**db[best], "material": best, "source": f"Partial match: {best}"}
    return {
        "nu": 1e-3, "rho": 1000.0, "Tmelt": 220.0, "Tmold": 50.0,
        "press_mpa": 70.0, "vel_mms": 80.0,
        "material": material_name, "source": "Default (not in DB)"
    }


def list_available_materials() -> list:
    db = load_material_db(MATERIAL_FILE)
    return sorted(db.keys())


# ═══════════════════════════════════════════════════════════
# 3D 시각화 함수들
# ═══════════════════════════════════════════════════════════

def load_stl_file(uploaded_file):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp:
            tmp.write(uploaded_file.getbuffer())
            tmp_path = tmp.name
        mesh = trimesh.load(tmp_path, force='mesh')
        if isinstance(mesh, trimesh.base.Trimesh) and len(mesh.faces) > 0:
            return mesh
        loaded = trimesh.load(tmp_path)
        if isinstance(loaded, trimesh.base.Trimesh) and len(loaded.faces) > 0:
            return loaded
        elif hasattr(loaded, 'geometry') and loaded.geometry:
            geom_list = [g for g in loaded.geometry.values()
                         if isinstance(g, trimesh.base.Trimesh) and len(g.faces) > 0]
            if geom_list:
                return trimesh.util.concatenate(geom_list)
        st.error("Could not read mesh from STL file. Please check the file.")
        return None
    except Exception as e:
        st.error(f"STL load error: {e}")
        return None


def visualize_mesh_with_gate(mesh: trimesh.Trimesh, gate_pos: list = None):
    try:
        vertices = mesh.vertices.copy()
        faces = mesh.faces.copy()
        if len(vertices) == 0 or len(faces) == 0:
            st.error("Mesh data is empty.")
            return None

        bounds = mesh.bounds
        center = (bounds[0] + bounds[1]) / 2.0
        scale  = float(np.max(bounds[1] - bounds[0]))
        if scale < 1e-9:
            scale = 1.0
        vn = ((vertices - center) / scale * 2.0)

        MAX_FACES = 8000
        if len(faces) > MAX_FACES:
            idx = np.random.choice(len(faces), MAX_FACES, replace=False)
            faces_ds = faces[idx]
        else:
            faces_ds = faces

        v0 = vn[faces_ds[:, 0]]
        v1 = vn[faces_ds[:, 1]]
        v2 = vn[faces_ds[:, 2]]
        normals = np.cross(v1 - v0, v2 - v0)
        nlen = np.linalg.norm(normals, axis=1, keepdims=True)
        nlen[nlen < 1e-9] = 1.0
        normals /= nlen

        light = np.array([0.6, 0.8, 1.0])
        light /= np.linalg.norm(light)
        brightness = np.clip(np.dot(normals, light), 0.1, 1.0)

        tri_centers = (v0 + v1 + v2) / 3.0
        z_order = np.argsort(tri_centers[:, 2])

        has_gate = gate_pos and len(gate_pos) == 3
        if has_gate:
            gn = ((np.array(gate_pos, dtype=float) - center) / scale * 2.0).tolist()
        else:
            gn = [0.0, 0.0, 0.0]

        tri_data = []
        for fi in z_order:
            f = faces_ds[fi]
            b = float(brightness[fi])
            tri_data.append([
                float(vn[f[0],0]), float(vn[f[0],1]), float(vn[f[0],2]),
                float(vn[f[1],0]), float(vn[f[1],1]), float(vn[f[1],2]),
                float(vn[f[2],0]), float(vn[f[2],1]), float(vn[f[2],2]),
                b
            ])

        tri_json  = json.dumps(tri_data)
        gate_json = json.dumps(gn)
        has_gate_js = "true" if has_gate else "false"

        html = f"""<!DOCTYPE html>
<html style="height:100%;margin:0;padding:0;">
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{
  height: 100%;
  background: #111827;
  font-family: monospace;
  color: #9ca3af;
  overflow: hidden;
}}
body {{ display:flex; flex-direction:column; }}
#wrap {{
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}}
canvas {{
  display: block;
  width:  100%;
  height: 100%;
  cursor: grab;
}}
canvas:active {{ cursor: grabbing; }}
#hud {{ position:absolute; top:6px; left:8px; font-size:11px;
        background:rgba(0,0,0,.55); padding:3px 8px; border-radius:4px;
        pointer-events:none; }}
#legend {{ position:absolute; bottom:6px; left:8px; font-size:11px;
           background:rgba(0,0,0,.55); padding:3px 8px; border-radius:4px;
           pointer-events:none; }}
#bar {{
  flex: 0 0 36px;
  width: 100%;
  padding: 4px 10px;
  display: flex;
  gap: 12px;
  background: #1f2937;
  font-size: 11px;
  align-items: center;
}}
button {{ background:#374151; color:#d1d5db; border:none; border-radius:4px;
          padding:2px 10px; cursor:pointer; font-size:11px; }}
button:hover {{ background:#4b5563; }}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="c"></canvas>
  <div id="hud">LClick: Rotate &nbsp;|&nbsp; RClick/Mid: Pan &nbsp;|&nbsp; Shift+Drag: Pan &nbsp;|&nbsp; Scroll: Zoom</div>
  <div id="legend">
    <span style="color:#7ec8e3">■</span> Part &nbsp;
    {'<span style="color:#ff4444">●</span> Gate' if has_gate else ''}
  </div>
</div>
<div id="bar">
  <button onclick="resetView()">⟳ Reset</button>
  <button onclick="toggleWire()">⬡ Wire</button>
  <span id="info" style="color:#6b7280"></span>
</div>

<script>
const TRIS   = {tri_json};
const GATE   = {gate_json};
const HAS_GATE = {has_gate_js};
const N_TRIS = TRIS.length;

document.getElementById('info').textContent =
  N_TRIS.toLocaleString() + ' triangles';

const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
let W, H;

function resize() {{
  const wrap = document.getElementById('wrap');
  W = wrap.clientWidth  || 640;
  H = wrap.clientHeight || 400;
  canvas.width  = W;
  canvas.height = H;
  draw();
}}
window.addEventListener('resize', resize);

let rotX = 0.35, rotY = -0.5, zoom = 1.0;
let panX = 0, panY = 0;
let wireMode = false;

function resetView() {{
  rotX = 0.35; rotY = -0.5; zoom = 1.0; panX = 0; panY = 0;
  draw();
}}
function toggleWire() {{
  wireMode = !wireMode; draw();
}}

function project(x, y, z) {{
  let x1 =  x * Math.cos(rotY) + z * Math.sin(rotY);
  let z1 = -x * Math.sin(rotY) + z * Math.cos(rotY);
  let y2 =  y * Math.cos(rotX) - z1 * Math.sin(rotX);
  let z2 =  y * Math.sin(rotX) + z1 * Math.cos(rotX);
  const fov = 2.8 * zoom;
  const d = 3.5 + z2;
  if (d < 0.01) return null;
  const sx = W/2 + panX + (x1 * fov / d) * W * 0.42;
  const sy = H/2 + panY - (y2 * fov / d) * W * 0.42;
  return [sx, sy];
}}

function draw() {{
  ctx.clearRect(0, 0, W, H);
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, '#0f172a');
  grad.addColorStop(1, '#1e293b');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  ctx.strokeStyle = 'rgba(55,65,81,0.6)';
  ctx.lineWidth = 0.5;
  for (let g = -4; g <= 4; g++) {{
    const a = project(g * 0.25, -1, -1);
    const b = project(g * 0.25, -1,  1);
    const c = project(-1, -1, g * 0.25);
    const d_ = project( 1, -1, g * 0.25);
    if (a && b) {{ ctx.beginPath(); ctx.moveTo(a[0],a[1]); ctx.lineTo(b[0],b[1]); ctx.stroke(); }}
    if (c && d_) {{ ctx.beginPath(); ctx.moveTo(c[0],c[1]); ctx.lineTo(d_[0],d_[1]); ctx.stroke(); }}
  }}

  for (let i = 0; i < N_TRIS; i++) {{
    const t = TRIS[i];
    const p0 = project(t[0], t[1], t[2]);
    const p1 = project(t[3], t[4], t[5]);
    const p2 = project(t[6], t[7], t[8]);
    if (!p0 || !p1 || !p2) continue;
    const b = t[9];
    if (wireMode) {{
      ctx.strokeStyle = `rgba(126,200,227,${{0.3 + b * 0.4}})`;
      ctx.lineWidth = 0.4;
      ctx.beginPath(); ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]); ctx.closePath(); ctx.stroke();
    }} else {{
      const r = Math.round(40  + b * 90);
      const g = Math.round(90  + b * 110);
      const bl= Math.round(130 + b * 97);
      ctx.fillStyle   = `rgba(${{r}},${{g}},${{bl}},0.88)`;
      ctx.strokeStyle = `rgba(${{r}},${{g}},${{bl}},0.15)`;
      ctx.lineWidth   = 0.3;
      ctx.beginPath(); ctx.moveTo(p0[0], p0[1]); ctx.lineTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]); ctx.closePath(); ctx.fill(); ctx.stroke();
    }}
  }}

  if (HAS_GATE) {{
    const gp = project(GATE[0], GATE[1], GATE[2]);
    if (gp) {{
      ctx.beginPath(); ctx.arc(gp[0], gp[1], 12, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,68,68,0.18)'; ctx.fill();
      ctx.beginPath(); ctx.arc(gp[0], gp[1], 6, 0, Math.PI * 2);
      ctx.fillStyle = '#ff4444'; ctx.fill();
      ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1.5; ctx.stroke();
      ctx.fillStyle = '#ff8888'; ctx.font = 'bold 11px monospace';
      ctx.fillText('Gate', gp[0] + 10, gp[1] - 6);
    }}
  }}

  const axO = project(0,0,0);
  const axX = project(0.15,0,0);
  const axY = project(0,0.15,0);
  const axZ = project(0,0,0.15);
  if (axO && axX) {{ drawAxis(axO, axX, '#ef4444', 'X'); }}
  if (axO && axY) {{ drawAxis(axO, axY, '#22c55e', 'Y'); }}
  if (axO && axZ) {{ drawAxis(axO, axZ, '#3b82f6', 'Z'); }}
}}

function drawAxis(o, a, color, label) {{
  ctx.strokeStyle = color; ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.moveTo(o[0], o[1]); ctx.lineTo(a[0], a[1]); ctx.stroke();
  ctx.fillStyle = color; ctx.font = 'bold 10px monospace';
  ctx.fillText(label, a[0] + 2, a[1] - 2);
}}

let dragging = false, panDragging = false;
let lastX = 0, lastY = 0;
canvas.addEventListener('contextmenu', e => e.preventDefault());
canvas.addEventListener('mousedown', e => {{
  lastX = e.clientX; lastY = e.clientY;
  if (e.button === 2 || e.button === 1) {{ panDragging = true; }}
  else {{ dragging = true; }}
}});
window.addEventListener('mouseup', () => {{ dragging = false; panDragging = false; }});
window.addEventListener('mousemove', e => {{
  const dx = e.clientX - lastX; const dy = e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  if (panDragging || (dragging && e.shiftKey)) {{ panX += dx; panY += dy; draw(); }}
  else if (dragging) {{
    rotY += dx * 0.012; rotX += dy * 0.012;
    rotX = Math.max(-Math.PI/2, Math.min(Math.PI/2, rotX)); draw();
  }}
}});
canvas.addEventListener('wheel', e => {{
  e.preventDefault();
  zoom *= (e.deltaY > 0) ? 0.92 : 1.09;
  zoom = Math.max(0.2, Math.min(8, zoom)); draw();
}}, {{ passive: false }});

let t0x=0, t0y=0, pinchD0=0;
canvas.addEventListener('touchstart', e => {{
  if (e.touches.length === 1) {{ t0x = e.touches[0].clientX; t0y = e.touches[0].clientY; }}
  else if (e.touches.length === 2) {{
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    pinchD0 = Math.sqrt(dx*dx + dy*dy);
  }}
  e.preventDefault();
}}, {{passive:false}});
canvas.addEventListener('touchmove', e => {{
  if (e.touches.length === 1) {{
    rotY += (e.touches[0].clientX - t0x) * 0.012;
    rotX += (e.touches[0].clientY - t0y) * 0.012;
    t0x = e.touches[0].clientX; t0y = e.touches[0].clientY;
  }} else if (e.touches.length === 2) {{
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const d  = Math.sqrt(dx*dx + dy*dy);
    zoom *= d / pinchD0; zoom = Math.max(0.2, Math.min(8, zoom)); pinchD0 = d;
  }}
  draw(); e.preventDefault();
}}, {{passive:false}});

resize();
</script>
</body>
</html>"""
        return html
    except Exception as e:
        st.error(f"3D visualization error: {e}")
        return None


# ═══════════════════════════════════════════════════════════
# 게이트 위치 추천 함수들
# ═══════════════════════════════════════════════════════════

def snap_to_mesh_surface(mesh: trimesh.Trimesh, point: np.ndarray) -> np.ndarray:
    try:
        triangles = mesh.vertices[mesh.faces]
        tri_centers = triangles.mean(axis=1)
        dists = np.linalg.norm(tri_centers - point, axis=1)
        closest_tri_idx = int(np.argmin(dists))
        return tri_centers[closest_tri_idx]
    except Exception:
        return point


def suggest_gate_positions(mesh: trimesh.Trimesh) -> list:
    suggestions = []
    try:
        bounds = mesh.bounds
        center = mesh.centroid
        dims   = bounds[1] - bounds[0]

        pt1 = np.array([center[0], center[1], bounds[0][2]])
        suggestions.append({"label": "Bottom-Center",
                             "position": snap_to_mesh_surface(mesh, pt1).tolist(),
                             "reason": "Balanced fill"})

        axis = int(np.argmax(dims))
        pt2  = center.copy(); pt2[axis] = bounds[0][axis]
        axis_label = ["X-Min Side", "Y-Min Side", "Z-Min Side"][axis]
        suggestions.append({"label": axis_label,
                             "position": snap_to_mesh_surface(mesh, pt2).tolist(),
                             "reason": "Fill along longest axis"})

        pt3 = np.array([center[0], center[1], bounds[1][2]])
        suggestions.append({"label": "Top-Center (Balanced)",
                             "position": snap_to_mesh_surface(mesh, pt3).tolist(),
                             "reason": "Top-center fill"})
    except Exception as e:
        st.warning(f"Gate suggestion error: {e}")
    return suggestions


def calc_gate_size_recommendation(mesh: trimesh.Trimesh, material: str) -> dict:
    try:
        bounds   = mesh.bounds
        dims     = bounds[1] - bounds[0]
        vol_mm3  = max(abs(float(mesh.volume)), 1.0)
        try:
            surf_mm2 = float(mesh.area)
        except Exception:
            surf_mm2 = 2.0 * (dims[0]*dims[1] + dims[1]*dims[2] + dims[2]*dims[0])

        t_wall = float(np.sort(dims)[0]) * 0.5
        t_wall = max(t_wall, 0.3)

        mat_upper = material.upper()
        is_mim = any(kw in mat_upper for kw in ["CATAMOLD", "WAXBASE", "MIM", "METAL", "SS", "316", "304"])

        if is_mim:
            process_label = "MIM (Metal Injection Molding)"
            t_gate = round(max(0.6 * t_wall, 0.5), 2)
            w_gate = round(max(2.0 * t_gate,  1.0), 2)
            formula_t = "t = 0.60 × t_wall (MPIF/German guideline)"
            formula_w = "W = 2.0 × t  (W:t ratio = 2:1)"
            shear_limit = 10000
        else:
            process_label = "Plastic Injection Molding"
            t_gate = round(max(0.5 * t_wall, 0.4), 2)
            w_gate = round(max(0.9 * np.sqrt(surf_mm2) / 30.0, t_gate * 1.5), 2)
            formula_t = "t = 0.50 × t_wall (Fattori, Plastics Technology)"
            formula_w = "W = 0.9 × √A_surface / 30  (unit: mm)"
            shear_limit = 40000

        d_gate = round(2.0 * np.sqrt(w_gate * t_gate / np.pi), 2)
        d_gate = max(d_gate, 0.5)

        Q_mm3s  = vol_mm3 / 1.0
        sr_rect = 6.0 * Q_mm3s / max(w_gate * t_gate**2, 1e-6)
        sr_circ = 32.0 * Q_mm3s / max(np.pi * d_gate**3, 1e-6)

        return {
            "process": process_label, "is_mim": is_mim,
            "t_wall_est": round(t_wall, 2), "t_gate": t_gate,
            "w_gate": w_gate, "d_gate": d_gate,
            "formula_t": formula_t, "formula_w": formula_w,
            "shear_rect": int(sr_rect), "shear_circ": int(sr_circ),
            "shear_limit": shear_limit,
            "warn_rect": sr_rect > shear_limit,
            "warn_circ": sr_circ > shear_limit,
            "vol_mm3": round(vol_mm3, 1), "surf_mm2": round(surf_mm2, 1),
        }
    except Exception as e:
        return {"error": str(e), "d_gate": 2.0, "w_gate": 3.0, "t_gate": 1.5, "is_mim": True}


def get_ai_gate_advice(mesh: trimesh.Trimesh, material_name: str):
    if not GEMINI_API_KEY:
        return None
    try:
        props = get_material_properties(material_name)
        vol   = abs(mesh.volume)
        dims  = mesh.bounds[1] - mesh.bounds[0]
        prompt = (
            f"Metal Injection Molding (MIM) simulation. "
            f"Material: {props.get('material', 'unknown')}, "
            f"Viscosity: {props.get('nu', 0):.2e} m²/s, "
            f"Density: {props.get('rho', 0):.0f} kg/m³, "
            f"Part volume: {vol:.1f} mm³, "
            f"Bounding box: {dims[0]:.1f} × {dims[1]:.1f} × {dims[2]:.1f} mm. "
            f"추천 게이트 위치와 이유를 2문장으로 설명하세요 (한글)."
        )
        gemini_url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash-lite:generateContent?key={GEMINI_API_KEY}"
        )
        response = requests.post(
            gemini_url,
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}],
                  "generationConfig": {"maxOutputTokens": 200, "temperature": 0.3}},
            timeout=10
        )
        if response.status_code == 200:
            data   = response.json()
            advice = (data.get("candidates", [{}])[0]
                          .get("content", {}).get("parts", [{}])[0]
                          .get("text", "").strip())
            return advice if advice else None
    except Exception as e:
        st.warning(f"Gemini AI 조언 조회 오류: {e}")
    return None


# ═══════════════════════════════════════════════════════════
# Oracle Cloud API 함수들
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=30, show_spinner=False)
def check_api_connection(api_url: str = None) -> tuple[bool, str]:
    url = api_url or ORACLE_API_URL
    try:
        response = requests.get(f"{url}/health", timeout=5)
        if response.status_code == 200:
            return True, "연결됨"
        return False, f"HTTP {response.status_code}"
    except requests.exceptions.ConnectionError:
        return False, f"서버에 연결할 수 없습니다 ({url})"
    except requests.exceptions.Timeout:
        return False, "연결 시간 초과 (5s)"
    except Exception as e:
        return False, str(e)


def submit_simulation(stl_file_bytes: bytes, params: dict) -> dict:
    """시뮬레이션 요청 제출 — wall_friction_k, flow_decay 포함"""
    try:
        url     = f"{ORACLE_API_URL}/api/simulate"
        headers = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        files   = {"stl_file": ("part.stl", stl_file_bytes, "application/octet-stream")}

        data = {
            "gate_x":          params.get("gate_x",          0),
            "gate_y":          params.get("gate_y",          0),
            "gate_z":          params.get("gate_z",          0),
            "gate_dia":        params.get("gate_dia",        2.0),
            "vel_mms":         params.get("vel_mms",         80),
            "etime":           params.get("etime",           1.0),
            "num_frames":      params.get("num_frames",      15),
            "mesh_res_mm":     params.get("mesh_res_mm",     0.5),
            # ★ 신규 파라미터
            "wall_friction_k": params.get("wall_friction_k", 3.0),
            "flow_decay":      params.get("flow_decay",      0.5),
        }

        response = requests.post(
            url, headers=headers, files=files, data=data, timeout=30
        )
        if response.status_code in (200, 202):
            return response.json()
        else:
            st.error(f"시뮬레이션 제출 실패: {response.status_code}")
            return None
    except Exception as e:
        st.error(f"API 오류: {e}")
        return None


def get_job_status(job_id: str) -> dict:
    try:
        url      = f"{ORACLE_API_URL}/api/jobs/{job_id}"
        headers  = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code in (200, 202):
            return response.json()
        return None
    except Exception as e:
        st.warning(f"상태 조회 오류: {e}")
        return None


def get_results(job_id: str) -> dict:
    try:
        url      = f"{ORACLE_API_URL}/api/results/{job_id}"
        headers  = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code in (200, 202):
            return response.json()
        return None
    except Exception as e:
        st.warning(f"결과 조회 오류: {e}")
        return None


def get_frames(job_id: str) -> tuple:
    try:
        url      = f"{ORACLE_API_URL}/api/frames/{job_id}"
        headers  = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            data   = response.json()
            frames = data.get("frames", [])
            if not frames:
                return [], "서버 응답은 성공했지만 frames 배열이 비어 있습니다."
            return frames, None
        elif response.status_code == 404:
            try:
                detail   = response.json()
                tip      = detail.get("tip", "")
                searched = detail.get("searched", [])
                msg      = f"404 — {detail.get('error', 'Not found')}"
                if tip:      msg += f"\n💡 {tip}"
                if searched: msg += f"\n탐색한 경로: {searched}"
            except Exception:
                msg = "404 — frames 디렉토리를 찾을 수 없습니다."
            return [], msg
        elif response.status_code == 400:
            try:
                detail = response.json().get("error", response.text)
            except Exception:
                detail = response.text
            return [], f"400 — {detail}"
        else:
            return [], f"HTTP {response.status_code}: {response.text[:200]}"
    except requests.exceptions.Timeout:
        return [], "요청 시간 초과 (60s). 프레임 수가 너무 많거나 서버가 느릴 수 있습니다."
    except Exception as e:
        return [], f"네트워크 오류: {e}"


def get_voxel_data(job_id: str):
    try:
        url      = f"{ORACLE_API_URL}/api/voxels/{job_id}"
        headers  = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code == 200:
            import io
            buf     = io.BytesIO(response.content)
            npz     = np.load(buf)
            coords  = npz["coords"].astype(np.float32)
            weights = npz["weights"].astype(np.float32)
            return coords, weights
        return None, None
    except Exception as e:
        st.warning(f"복셀 데이터 조회 오류: {e}")
        return None, None

def get_voxel_data_full(job_id: str) -> dict | None:
    """
    voxel_data.npz의 모든 필드를 dict로 반환.
    Phase 탭 전용. 기존 get_voxel_data()는 건드리지 않음.
    """
    try:
        url     = f"{ORACLE_API_URL}/api/voxels/{job_id}"
        headers = {"Authorization": f"Bearer {ORACLE_API_KEY}"}
        response = requests.get(url, headers=headers, timeout=60)
        if response.status_code != 200:
            return None
        import io
        buf = io.BytesIO(response.content)
        npz = np.load(buf)
        result = {}
        for key in npz.files:
            result[key] = npz[key].astype(np.float32)
        return result  # {"coords": ..., "weights": ..., "display_weights": ..., "pressure": ...}
    except Exception as e:
        st.warning(f"복셀 전체 데이터 조회 오류: {e}")
        return None


def build_webgl_pressure_viewer(
    coords: np.ndarray,
    pressure_norm: np.ndarray,
    max_points: int = 8000,
    mode: str = "pressure",   # "pressure" | "airtrap"
    vent_coords: np.ndarray = None,
) -> str:
    """
    압력 분포 / 에어트랩 공용 3D 정적 뷰어 (Canvas 2D).

    mode="pressure":
        pressure_norm = 0~1 정규화 압력
        색상: 파랑(저압) → 초록 → 빨강(고압)

    mode="airtrap":
        pressure_norm = 복셀 타입 (0.0=표면복셀, 1.0=에어트랩)
        색상: 0.0 → dim blue (작은 점), 1.0 → bright cyan (큰 점)
        vent_coords: 벤트 추천 좌표 배열 (N,3) — 주황 다이아몬드로 표시

    Streamlit iframe에서 clientWidth가 0으로 잡히는 버그를
    requestAnimationFrame 지연 resize로 해결합니다.
    """
    import json as _json

    N = len(coords)
    if N == 0:
        return "<p>복셀 데이터 없음</p>"

    if N > max_points:
        idx      = np.linspace(0, N - 1, max_points, dtype=int)
        coords_s = coords[idx]
        p_norm_s = pressure_norm[idx]
    else:
        coords_s = coords
        p_norm_s = pressure_norm

    c_min    = coords_s.min(axis=0)
    c_max    = coords_s.max(axis=0)
    scale    = float(np.maximum(c_max - c_min, 1e-6).max())
    center   = (c_min + c_max) / 2.0
    coords_n = ((coords_s - center) / scale * 2.0).astype(np.float32)

    xyzp      = np.column_stack([coords_n, p_norm_s])
    xyzp_json = _json.dumps([[round(float(v), 3) for v in row] for row in xyzp])

    # 벤트 좌표 정규화
    vent_json = "[]"
    if mode == "airtrap" and vent_coords is not None and len(vent_coords) > 0:
        vc_n = ((np.array(vent_coords, dtype=np.float32) - center) / scale * 2.0)
        vent_json = _json.dumps([[round(float(v), 3) for v in row] for row in vc_n])

    # 모드별 HUD/범례 텍스트
    if mode == "airtrap":
        hud_html = """
  <div><span style="color:#557a99">에어트랩 </span>
       <span style="color:#00ccff">■</span> 에어트랩 &nbsp;
       <span style="color:#1a3a6a">■</span> 표면 복셀 &nbsp;
       <span style="color:#ff6600">◆</span> 추천 벤트</div>
  <div style="font-size:9px;color:#33556e;margin-top:4px">
    좌클릭:회전 | 스크롤:줌 | 우클릭:이동</div>"""
        legend_html = ""
        color_fn_js = """
function pointColor(p) {
  // p=0 → 표면복셀(dim blue), p=1 → 에어트랩(bright cyan)
  if (p >= 0.5) return {r:0,   g:180, b:255, a:0.90, radius:3.5};
  else          return {r:20,  g:60,  b:120, a:0.35, radius:1.8};
}"""
    else:
        hud_html = """
  <div><span style="color:#557a99">압력 분포 </span>
       <span style="color:#ff4444">■</span>고압 →
       <span style="color:#4444ff">■</span>저압</div>
  <div style="font-size:9px;color:#33556e;margin-top:4px">
    좌클릭:회전 | 스크롤:줌 | 우클릭:이동</div>"""
        legend_html = """
<div id="legend">
  <canvas id="legCvs" width="120" height="12"></canvas>
  <div style="display:flex;justify-content:space-between;color:#557a99">
    <span>저압</span><span>고압</span></div>
</div>"""
        color_fn_js = """
function pointColor(p) {
  const r = p < 0.5 ? Math.round(p*2*30)  : Math.round(30  + (p-0.5)*2*225);
  const g = p < 0.5 ? Math.round(p*2*220) : Math.round(220 - (p-0.5)*2*180);
  const b = p < 0.5 ? Math.round(255-p*2*225) : 30;
  return {r, g, b, a:0.85, radius:2.5};
}"""

    legend_init_js = "" if mode == "airtrap" else """
(function(){
  const lc = document.getElementById('legCvs');
  if (!lc) return;
  const lx = lc.getContext('2d');
  const grd = lx.createLinearGradient(0,0,120,0);
  grd.addColorStop(0,'rgb(30,30,255)');
  grd.addColorStop(0.5,'rgb(30,220,30)');
  grd.addColorStop(1,'rgb(255,30,30)');
  lx.fillStyle=grd; lx.fillRect(0,0,120,12);
})();"""

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:100%;height:100%;background:#07101f;
           font-family:'Courier New',monospace;color:#8ecfff;overflow:hidden}}
#wrap{{position:relative;width:100%;height:100%}}
canvas#c{{position:absolute;top:0;left:0;width:100%;height:100%;
          display:block;cursor:grab}}
canvas#c:active{{cursor:grabbing}}
#hud{{position:absolute;top:10px;left:12px;font-size:11px;
      background:rgba(0,10,30,.75);border:1px solid #1a3a5c;
      border-radius:6px;padding:6px 12px;line-height:1.8;
      pointer-events:none;z-index:10}}
#legend{{position:absolute;bottom:40px;right:12px;font-size:10px;
         background:rgba(0,10,30,.75);border:1px solid #1a3a5c;
         border-radius:6px;padding:6px 10px;z-index:10}}
#legend canvas{{width:120px;height:12px;display:block;margin-bottom:3px}}
</style></head><body>
<div id="wrap">
<canvas id="c"></canvas>
<div id="hud">{hud_html}</div>
{legend_html}
</div>
<script>
const XYZP = {xyzp_json};
const VENTS = {vent_json};
const canvas = document.getElementById('c');
const ctx = canvas.getContext('2d');
let W=0, H=0;

function resize() {{
  const wrap = document.getElementById('wrap');
  const cw = wrap.clientWidth  || document.body.clientWidth  || 800;
  const ch = wrap.clientHeight || document.body.clientHeight || 500;
  if (cw < 10 || ch < 10) {{
    requestAnimationFrame(resize);
    return;
  }}
  W = canvas.width  = cw;
  H = canvas.height = ch;
  draw();
}}
window.addEventListener('resize', () => {{ resize(); }});
// 첫 렌더: Streamlit iframe 마운트 후 크기가 확정될 때까지 RAF 대기
requestAnimationFrame(resize);

{color_fn_js}
{legend_init_js}

let rotX=0.35, rotY=-0.5, zoom=1.0, panX=0, panY=0;
let isDrag=false, isPan=false, lastMX=0, lastMY=0;

function project(x,y,z) {{
  const x1 =  x*Math.cos(rotY)+z*Math.sin(rotY);
  const z1 = -x*Math.sin(rotY)+z*Math.cos(rotY);
  const y2 =  y*Math.cos(rotX)-z1*Math.sin(rotX);
  const z2 =  y*Math.sin(rotX)+z1*Math.cos(rotX);
  const fov=2.8*zoom, d=3.5+z2;
  if(d<0.01) return null;
  return [W/2+panX+(x1*fov/d)*W*0.42, H/2+panY-(y2*fov/d)*W*0.42, z2];
}}

function draw() {{
  if(W===0 || H===0) return;
  ctx.clearRect(0,0,W,H);
  const grd=ctx.createLinearGradient(0,0,0,H);
  grd.addColorStop(0,'#0f172a'); grd.addColorStop(1,'#1e293b');
  ctx.fillStyle=grd; ctx.fillRect(0,0,W,H);

  const pts = XYZP.map(r => {{
    const p=project(r[0],r[1],r[2]);
    return p ? {{sx:p[0],sy:p[1],depth:p[2],pv:r[3]}} : null;
  }}).filter(Boolean).sort((a,b)=>a.depth-b.depth);

  pts.forEach(pt => {{
    const c = pointColor(pt.pv);
    ctx.beginPath();
    ctx.arc(pt.sx, pt.sy, c.radius, 0, Math.PI*2);
    ctx.fillStyle = `rgba(${{c.r}},${{c.g}},${{c.b}},${{c.a}})`;
    ctx.fill();
  }});

  // 벤트 위치 — 주황 다이아몬드
  VENTS.forEach((v, i) => {{
    const p = project(v[0],v[1],v[2]);
    if (!p) return;
    const [sx, sy] = p;
    const s = 9;
    ctx.beginPath();
    ctx.moveTo(sx,    sy-s);
    ctx.lineTo(sx+s,  sy);
    ctx.lineTo(sx,    sy+s);
    ctx.lineTo(sx-s,  sy);
    ctx.closePath();
    ctx.fillStyle   = '#ff6600';
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth   = 1.5;
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = '#ffcc88';
    ctx.font = 'bold 10px Courier New';
    ctx.fillText('V'+(i+1), sx+12, sy-4);
  }});
}}

canvas.addEventListener('mousedown',e=>{{
  isDrag=true; isPan=(e.button===2||e.button===1||e.shiftKey);
  lastMX=e.clientX; lastMY=e.clientY; e.preventDefault();
}});
window.addEventListener('mouseup',()=>{{isDrag=false; isPan=false;}});
window.addEventListener('mousemove',e=>{{
  if(!isDrag) return;
  const dx=e.clientX-lastMX, dy=e.clientY-lastMY;
  lastMX=e.clientX; lastMY=e.clientY;
  if(isPan){{ panX+=dx; panY+=dy; }}
  else{{ rotY-=dx*0.01; rotX+=dy*0.01; }}
  draw();
}});
canvas.addEventListener('wheel',e=>{{
  e.preventDefault();
  zoom=Math.max(0.3,Math.min(5,zoom*(e.deltaY>0?0.93:1.08)));
  draw();
}},{{passive:false}});
canvas.addEventListener('contextmenu',e=>e.preventDefault());
</script></body></html>"""
    return html


def build_webgl_flow_viewer(
    coords: np.ndarray, weights: np.ndarray,
    mesh_trimesh=None, num_frames: int = 15, max_voxels: int = 40000,
    gate_dia_mm: float = None, gate_width_mm: float = None, gate_height_mm: float = None,
) -> str:
    import json as _json

    N = len(coords)
    if N == 0:
        return "<p>복셀 데이터 없음</p>"

    c_min  = coords.min(axis=0)
    c_max  = coords.max(axis=0)
    scale  = float(np.maximum(c_max - c_min, 1e-6).max())
    center = (c_min + c_max) / 2.0

    def normalize(pts):
        return ((pts - center) / scale * 2.0).astype(np.float32)

    if N > max_voxels:
        idx       = np.linspace(0, N - 1, max_voxels, dtype=int)
        coords_s  = coords[idx]
        weights_s = weights[idx]
    else:
        coords_s  = coords
        weights_s = weights

    if mesh_trimesh is not None:
        try:
            inside_mask = mesh_trimesh.contains(coords_s)
            n_inside    = int(inside_mask.sum())
            if n_inside >= 50:
                coords_s  = coords_s[inside_mask]
                weights_s = weights_s[inside_mask]
        except Exception:
            pass

    coords_n   = normalize(coords_s)
    voxel_size_n = min(0.06, max(0.002, 2.0 / (N ** (1/3))))

    if gate_dia_mm is not None:
        gate_r_n   = float(gate_dia_mm / scale)
        gate_w_n   = gate_r_n * 2.0
        gate_h_n   = gate_r_n * 2.0
        gate_shape_js = "circular"
    elif gate_width_mm is not None and gate_height_mm is not None:
        gate_w_n   = float(gate_width_mm  / scale * 2.0)
        gate_h_n   = float(gate_height_mm / scale * 2.0)
        gate_r_n   = float(np.sqrt(gate_width_mm * gate_height_mm / np.pi) / scale)
        gate_shape_js = "rectangular"
    else:
        gate_r_n   = voxel_size_n * 1.2
        gate_w_n   = gate_r_n * 2.0
        gate_h_n   = gate_r_n * 2.0
        gate_shape_js = "circular"
    gate_r_n = max(gate_r_n, voxel_size_n * 0.5)

    M         = len(coords_n)
    xyzw_flat = np.column_stack([coords_n, weights_s]).astype(np.float32)
    xyzw_b64  = base64.b64encode(xyzw_flat.tobytes()).decode()

    mesh_wire_json  = "null"
    mesh_faces_json = "null"
    if mesh_trimesh is not None:
        try:
            verts_n = normalize(np.array(mesh_trimesh.vertices, dtype=np.float32))
            faces   = np.array(mesh_trimesh.faces, dtype=np.int32)
            MAX_FACES = 12000
            if len(faces) > MAX_FACES:
                idx_f = np.random.choice(len(faces), MAX_FACES, replace=False)
                faces = faces[idx_f]
            edges = set()
            for f in faces:
                for i in range(3):
                    edges.add(tuple(sorted([int(f[i]), int(f[(i+1)%3])])))
            wire_pts = []
            for e in edges:
                wire_pts.extend(verts_n[e[0]].tolist())
                wire_pts.extend(verts_n[e[1]].tolist())
            mesh_wire_json = _json.dumps([round(v, 4) for v in wire_pts])
            face_pts = []
            for f in faces:
                for vi in f:
                    face_pts.extend(verts_n[vi].tolist())
            mesh_faces_json = _json.dumps([round(v, 4) for v in face_pts])
        except Exception:
            pass

    nf       = num_frames
    thr_list = [round(float(t), 4) for t in np.linspace(0, 1, nf + 1)[1:]]
    thr_json = _json.dumps(thr_list)
    vs       = round(float(voxel_size_n), 5)
    js_gate_r     = round(gate_r_n,      5)
    js_gate_w     = round(gate_w_n,      5)
    js_gate_h     = round(gate_h_n,      5)
    js_gate_shape = gate_shape_js

    # (Three.js HTML은 원본과 동일 — 생략 없이 그대로 반환)
    html = f"""<!DOCTYPE html>
<html style="margin:0;padding:0;height:100%;">
<head>
<meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#07101f;overflow:hidden;font-family:'Courier New',monospace;color:#8ecfff;height:100vh;display:flex;flex-direction:column}}
#container{{flex:1;display:flex;flex-direction:row;min-height:0}}
#gizmoPanel{{width:6.25%;min-width:70px;max-width:90px;background:rgba(2,8,20,.95);border-right:1px solid #1a3a5c;display:flex;flex-direction:column;align-items:center;justify-content:center;flex-shrink:0;gap:6px;padding:8px 4px;}}
#gizmoPanel .glbl{{font-size:9px;color:#3a6a8a;text-align:center;line-height:1.4}}
#gizmoCvs{{border:1px solid #1e4060;border-radius:6px;background:rgba(0,6,18,.80)}}
#viewport{{flex:1;position:relative;min-width:0;min-height:0}}
#viewport canvas{{display:block;width:100%!important;height:100%!important}}
#hud{{position:absolute;top:10px;left:12px;font-size:11px;background:rgba(0,8,24,.78);border:1px solid #1a3a5c;border-radius:6px;padding:7px 13px;line-height:1.8;pointer-events:none;min-width:185px;z-index:10}}
#hud .val{{color:#4df0c0;font-weight:bold}}
#hud .lbl{{color:#4a6e88}}
#rpanel{{position:absolute;top:10px;right:10px;z-index:20;background:rgba(2,8,22,.92);border:1px solid #1e3a5c;border-radius:8px;padding:10px 12px;width:220px;font-family:'Courier New',monospace;box-shadow:0 2px 16px rgba(0,0,0,.6);}}
#rpanel.collapsed #rpbody{{display:none}}
#rphead{{display:flex;justify-content:space-between;align-items:center;cursor:pointer;margin-bottom:8px;}}
#rphead span{{font-size:11px;color:#4df0c0;font-weight:bold;letter-spacing:.5px}}
#rptoggle{{font-size:13px;color:#3a6a8a}}
.rrow{{display:flex;align-items:center;justify-content:space-between;margin-bottom:7px;gap:4px}}
.rlbl{{font-size:10px;color:#3a6a8a;white-space:nowrap;min-width:78px}}
.rval{{font-size:10px;color:#4df0c0;min-width:32px;text-align:right}}
.rslider{{flex:1;accent-color:#4df0c0;cursor:pointer;height:3px}}
.rsel{{flex:1;background:#0d1e35;border:1px solid #1e3a5c;color:#c8e0ff;font-size:10px;border-radius:4px;padding:2px 4px;cursor:pointer}}
.rdiv{{border:none;border-top:1px solid #1a3050;margin:7px 0}}
.rtitle{{font-size:9px;color:#2a5070;text-transform:uppercase;letter-spacing:1px;margin-bottom:5px}}
#ctrl{{background:rgba(4,10,24,.95);border-top:1px solid #1a3a5c;padding:9px 14px;display:flex;flex-direction:column;gap:7px;z-index:10}}
.crow{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
.btn{{background:rgba(13,110,253,.13);border:1px solid #1a3a5c;color:#8ecfff;border-radius:5px;padding:3px 11px;cursor:pointer;font-size:12px;transition:background .15s,border-color .15s;white-space:nowrap}}
.btn:hover{{background:rgba(77,240,192,.18);border-color:#4df0c0;color:#4df0c0}}
.btn.on{{background:rgba(77,240,192,.25);border-color:#4df0c0;color:#4df0c0}}
#progwrap{{flex:1;min-width:120px;height:18px;position:relative;cursor:pointer}}
#progbg{{position:absolute;top:50%;transform:translateY(-50%);width:100%;height:4px;background:#1a3a5c;border-radius:2px}}
#progfill{{position:absolute;top:50%;transform:translateY(-50%);height:4px;width:0%;background:linear-gradient(90deg,#0d6efd,#4df0c0);border-radius:2px}}
#progthumb{{position:absolute;top:50%;left:0%;transform:translate(-50%,-50%);width:14px;height:14px;background:#4df0c0;border-radius:50%;box-shadow:0 0 6px #4df0c0;cursor:grab}}
#fc{{font-size:11px;color:#4df0c0;min-width:55px;text-align:right}}
#spdlbl{{color:#4df0c0;font-size:11px}}
input[type=range]{{accent-color:#4df0c0;cursor:pointer}}
</style>
</head>
<body>
<div id="container">
  <div id="gizmoPanel">
    <div class="glbl">XYZ<br>Axis</div>
    <canvas id="gizmoCvs" width="72" height="72"></canvas>
    <div class="glbl" style="font-size:8px;color:#1e4060;margin-top:4px">
      <span style="color:#ff5555">■</span> X<br>
      <span style="color:#55ff55">■</span> Y<br>
      <span style="color:#5599ff">■</span> Z
    </div>
  </div>
  <div id="viewport">
  <div id="hud">
    <div><span class="lbl">충진률&nbsp;</span><span class="val" id="hFill">0.0%</span></div>
    <div><span class="lbl">물리시간</span><span class="val" id="hTime">0.000 s</span></div>
    <div><span class="lbl">표시복셀</span><span class="val" id="hVox">0</span></div>
    <div style="margin-top:4px;font-size:9px;color:#2a4a60">좌클릭:회전 | 우클릭·중간:이동 | Shift+드래그:이동 | 스크롤:줌</div>
  </div>
  <div id="rpanel">
    <div id="rphead" onclick="toggleRPanel()">
      <span>⚙ 표시 설정</span><span id="rptoggle">▲</span>
    </div>
    <div id="rpbody">
      <div class="rtitle">색상 테마</div>
      <div class="rrow">
        <select class="rsel" id="selTheme" onchange="applyTheme(this.value)">
          <option value="blueyellow">🔵→🟡 파랑→노랑 (기본)</option>
          <option value="redwhite">🔴→⚪ 빨강→흰색</option>
          <option value="greenorange">🟢→🟠 초록→주황</option>
          <option value="rainbow">🌈 무지개</option>
          <option value="heat">🌡 열화상</option>
          <option value="cyan">🩵 시안 단색</option>
        </select>
      </div>
      <hr class="rdiv">
      <div class="rtitle">복셀</div>
      <div class="rrow">
        <span class="rlbl">형상</span>
        <select class="rsel" id="selVoxShape" onchange="setVoxShape(this.value)">
          <option value="box">■ 정육면체 (기본)</option>
          <option value="sphere">● 구</option>
          <option value="cylinder">⬤ 원기둥</option>
          <option value="octahedron">◆ 팔면체</option>
        </select>
      </div>
      <div class="rrow">
        <span class="rlbl">투명도</span>
        <input class="rslider" type="range" min="10" max="100" value="90"
               oninput="setVoxOpacity(this.value/100);document.getElementById('rvoxOp').textContent=this.value+'%'">
        <span class="rval" id="rvoxOp">90%</span>
      </div>
      <div class="rrow">
        <span class="rlbl">발광(emissive)</span>
        <input class="rslider" type="range" min="0" max="100" value="55"
               oninput="setEmissive(this.value/100);document.getElementById('rvoxEm').textContent=this.value+'%'">
        <span class="rval" id="rvoxEm">55%</span>
      </div>
      <div class="rrow">
        <span class="rlbl">광택(shininess)</span>
        <input class="rslider" type="range" min="0" max="150" value="60"
               oninput="setShininess(parseInt(this.value));document.getElementById('rvoxSh').textContent=this.value">
        <span class="rval" id="rvoxSh">60</span>
      </div>
      <div class="rrow">
        <span class="rlbl">크기</span>
        <input class="rslider" type="range" min="50" max="200" value="100"
               oninput="setVoxSize(this.value/100);document.getElementById('rvoxSz').textContent=this.value+'%'">
        <span class="rval" id="rvoxSz">100%</span>
      </div>
      <hr class="rdiv">
      <div class="rtitle">조명</div>
      <div class="rrow">
        <span class="rlbl">주변광</span>
        <input class="rslider" type="range" min="0" max="200" value="120"
               oninput="setAmbient(this.value/100);document.getElementById('rAmb').textContent=this.value+'%'">
        <span class="rval" id="rAmb">120%</span>
      </div>
      <div class="rrow">
        <span class="rlbl">방향광</span>
        <input class="rslider" type="range" min="0" max="200" value="100"
               oninput="setDirLight(this.value/100);document.getElementById('rDir').textContent=this.value+'%'">
        <span class="rval" id="rDir">100%</span>
      </div>
      <hr class="rdiv">
      <div class="rtitle">Wireframe</div>
      <div class="rrow">
        <span class="rlbl">투명도</span>
        <input class="rslider" type="range" min="0" max="100" value="18"
               oninput="setWireOp(this.value/100);document.getElementById('rwireOp').textContent=this.value+'%'">
        <span class="rval" id="rwireOp">18%</span>
      </div>
      <div class="rrow">
        <span class="rlbl">색상</span>
        <input type="color" value="#ffffff"
               style="width:38px;height:20px;cursor:pointer;border:none;background:none"
               oninput="setWireColor(this.value)">
        <span class="rval" style="font-size:9px;color:#3a6a8a">선택</span>
      </div>
      <hr class="rdiv">
      <div class="rtitle">Solid Shell</div>
      <div class="rrow">
        <span class="rlbl">투명도</span>
        <input class="rslider" type="range" min="0" max="100" value="35"
               oninput="setSolidOp(this.value/100);document.getElementById('rsolOp').textContent=this.value+'%'">
        <span class="rval" id="rsolOp">35%</span>
      </div>
      <div class="rrow">
        <span class="rlbl">색상</span>
        <input type="color" value="#3a6080"
               style="width:38px;height:20px;cursor:pointer;border:none;background:none"
               oninput="setSolidColor(this.value)">
        <span class="rval" style="font-size:9px;color:#3a6a8a">선택</span>
      </div>
      <div class="rrow">
        <span class="rlbl">측면</span>
        <select class="rsel" id="selSolidSide" onchange="setSolidSide(this.value)">
          <option value="double">양면 (기본)</option>
          <option value="front">앞면만</option>
          <option value="back">뒷면만</option>
        </select>
      </div>
      <hr class="rdiv">
      <div class="rtitle">배경</div>
      <div class="rrow">
        <span class="rlbl">배경색</span>
        <input type="color" value="#07101f"
               style="width:38px;height:20px;cursor:pointer;border:none;background:none"
               oninput="setBg(this.value)">
        <span class="rval" style="font-size:9px;color:#3a6a8a">선택</span>
      </div>
    </div>
  </div>
  </div>
</div>
<div id="ctrl">
  <div class="crow">
    <div id="progwrap">
      <div id="progbg"></div><div id="progfill"></div><div id="progthumb"></div>
    </div>
    <span id="fc">1 / {nf}</span>
  </div>
  <div class="crow">
    <button class="btn" id="btnPlay" onclick="togglePlay()">▶ Play</button>
    <button class="btn" id="btnReset" onclick="resetAnim()">↩ Reset</button>
    <button class="btn" id="btnRot" onclick="toggleAutoRot()">⟳ Auto</button>
    <button class="btn" id="btnWire" onclick="toggleWire()">⬡ Wire</button>
    <button class="btn" id="btnSolid" onclick="toggleSolid()">◼ Solid</button>
    <span style="font-size:11px;color:#4a6e88">Speed</span>
    <input id="spdRange" type="range" min="1" max="8" value="3" step="1"
           style="width:70px" oninput="onSpeed(this.value)">
    <span id="spdlbl">1.5×</span>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
const XYZW_B64={xyzw_b64 !r};const THRS={thr_json};const NF={nf};const VSIZE={vs};
const WIRE_PTS={mesh_wire_json};const FACE_PTS={mesh_faces_json};
const GATE_R={js_gate_r};const GATE_W={js_gate_w};const GATE_H={js_gate_h};
const GATE_SHAPE="{js_gate_shape}";
function b64toF32(b64){{const bin=atob(b64);const buf=new ArrayBuffer(bin.length);const u8=new Uint8Array(buf);for(let i=0;i<bin.length;i++)u8[i]=bin.charCodeAt(i);return new Float32Array(buf);}}
const raw=b64toF32(XYZW_B64);const M=raw.length/4;
const container=document.getElementById('container');const viewport=document.getElementById('viewport');
const renderer=new THREE.WebGLRenderer({{antialias:true,alpha:true}});
renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));renderer.setClearColor(0x07101f,1);
viewport.appendChild(renderer.domElement);
const scene=new THREE.Scene();const camera=new THREE.PerspectiveCamera(22,1,0.001,300);
camera.position.set(5.5,3.8,5.5);camera.lookAt(0,0,0);
const ambientLight=new THREE.AmbientLight(0xffffff,1.2);scene.add(ambientLight);
const dLight=new THREE.DirectionalLight(0xffffff,1.0);dLight.position.set(3,5,3);scene.add(dLight);
const dLight2=new THREE.DirectionalLight(0x8899ff,0.4);dLight2.position.set(-2,-2,-3);scene.add(dLight2);
let wireObj=null,solidObj=null;
if(WIRE_PTS&&WIRE_PTS.length>0){{const wGeo=new THREE.BufferGeometry();wGeo.setAttribute('position',new THREE.Float32BufferAttribute(WIRE_PTS,3));const wMat=new THREE.LineBasicMaterial({{color:0xffffff,transparent:true,opacity:0.18,depthWrite:false}});wireObj=new THREE.LineSegments(wGeo,wMat);scene.add(wireObj);}}
if(FACE_PTS&&FACE_PTS.length>0){{const fGeo=new THREE.BufferGeometry();fGeo.setAttribute('position',new THREE.Float32BufferAttribute(FACE_PTS,3));fGeo.computeVertexNormals();const fMat=new THREE.MeshPhongMaterial({{color:new THREE.Color(0x4488bb),emissive:new THREE.Color(0x0a1a2a),emissiveIntensity:0.6,transparent:true,opacity:0.35,side:THREE.DoubleSide,depthWrite:false,depthTest:true}});solidObj=new THREE.Mesh(fGeo,fMat);solidObj.renderOrder=2;scene.add(solidObj);}}
const THEMES={{blueyellow:w=>{{if(w<0.5){{const t=w*2;return[0.05+t*0.00,0.45+t*0.45,0.99+t*0.01];}}else{{const t=(w-0.5)*2;return[0.05+t*0.95,0.90,1.00-t*0.60];}}}},redwhite:w=>[1.0,w*0.85,w*0.85],greenorange:w=>{{if(w<0.5){{const t=w*2;return[0.04+t*0.60,0.80-t*0.10,0.10];}}else{{const t=(w-0.5)*2;return[0.64+t*0.36,0.70+t*0.20,0.10];}}}},rainbow:w=>{{const h=(1-w)*0.75,i=Math.floor(h*6),f=h*6-i;const lut=[[1,1*(1-(1-f)*1),1*(1-1)],[1*(1-f*1),1,1*(1-1)],[1*(1-1),1,1*(1-(1-f)*1)],[1*(1-1),1*(1-f*1),1],[1*(1-(1-f)*1),1*(1-1),1],[1,1*(1-1),1*(1-f*1)]];return lut[i%6];}},heat:w=>[Math.min(1,w*2),Math.max(0,Math.min(1,w*2-0.5)),Math.max(0,1-w*2)],cyan:w=>[0.05,0.40+w*0.55,0.70+w*0.30]}};
let currentTheme='blueyellow';
function weightToColor(w){{return(THEMES[currentTheme]||THEMES.blueyellow)(w);}}
const voxGeo=new THREE.BoxGeometry(VSIZE*0.92,VSIZE*0.92,VSIZE*0.92);
const voxMat=new THREE.MeshPhongMaterial({{transparent:true,opacity:0.90,shininess:60,emissiveIntensity:0.55}});
const instMesh=new THREE.InstancedMesh(voxGeo,voxMat,M);instMesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);scene.add(instMesh);
const _tmpColor=new THREE.Color();
function _applyInstanceColors(){{const fn=THEMES[currentTheme]||THEMES.blueyellow;for(let i=0;i<M;i++){{const c=fn(raw[i*4+3]);_tmpColor.setRGB(c[0],c[1],c[2]);instMesh.setColorAt(i,_tmpColor);}}if(instMesh.instanceColor)instMesh.instanceColor.needsUpdate=true;}}
_applyInstanceColors();
function rebuildColors(){{const fn=THEMES[currentTheme]||THEMES.blueyellow;for(let i=0;i<M;i++){{const c=fn(raw[i*4+3]);_tmpColor.setRGB(c[0],c[1],c[2]);instMesh.setColorAt(i,_tmpColor);}}if(instMesh.instanceColor)instMesh.instanceColor.needsUpdate=true;}}
function applyTheme(t){{currentTheme=t;rebuildColors();}}
let currentVoxShape='box';
function setVoxShape(shape){{currentVoxShape=shape;let newGeo;const s=VSIZE*0.92;switch(shape){{case'sphere':newGeo=new THREE.SphereGeometry(s*0.58,8,6);break;case'cylinder':newGeo=new THREE.CylinderGeometry(s*0.45,s*0.45,s*0.9,8);break;case'octahedron':newGeo=new THREE.OctahedronGeometry(s*0.62);break;default:newGeo=new THREE.BoxGeometry(s,s,s);break;}}instMesh.geometry.dispose();instMesh.geometry=newGeo;}}
function toggleRPanel(){{document.getElementById('rpanel').classList.toggle('collapsed');document.getElementById('rptoggle').textContent=document.getElementById('rpanel').classList.contains('collapsed')?'▼':'▲';}}
function setVoxOpacity(v){{voxMat.opacity=v;}}
function setEmissive(v){{voxMat.emissive=new THREE.Color(0.08*v,0.25*v,0.30*v);voxMat.emissiveIntensity=v;}}
function setShininess(v){{voxMat.shininess=v;}}
let voxScale=1.0;
function setVoxSize(v){{voxScale=v;setFrame(curFrame);}}
function setWireOp(v){{if(wireObj)wireObj.material.opacity=v;}}
function setWireColor(hex){{if(wireObj){{wireObj.material.color.set(hex);wireObj.material.needsUpdate=true;}}}}
function setSolidOp(v){{if(solidObj)solidObj.material.opacity=v;}}
function setSolidColor(hex){{if(solidObj){{solidObj.material.color.set(hex);solidObj.material.emissive.set(hex).multiplyScalar(0.3);solidObj.material.needsUpdate=true;}}}}
function setSolidSide(v){{if(!solidObj)return;solidObj.material.side=v==='front'?THREE.FrontSide:v==='back'?THREE.BackSide:THREE.DoubleSide;}}
function setBg(hex){{const c=parseInt(hex.replace('#',''),16);renderer.setClearColor(c,1);document.body.style.background=hex;}}
function setAmbient(v){{ambientLight.intensity=v;}}
function setDirLight(v){{dLight.intensity=v;}}
const dummy=new THREE.Object3D();
let gateIdx=0;for(let i=1;i<M;i++){{if(raw[i*4+3]<raw[gateIdx*4+3])gateIdx=i;}}
let gateObj;
if(GATE_SHAPE==='rectangular'){{gateObj=new THREE.Mesh(new THREE.BoxGeometry(GATE_W,GATE_H,GATE_H*0.5),new THREE.MeshPhongMaterial({{color:0xff3355,emissive:0x661122,transparent:true,opacity:0.9}}));}}
else{{gateObj=new THREE.Mesh(new THREE.SphereGeometry(GATE_R,16,12),new THREE.MeshPhongMaterial({{color:0xff3355,emissive:0x661122,transparent:true,opacity:0.9}}));}}
gateObj.position.set(raw[gateIdx*4],raw[gateIdx*4+1],raw[gateIdx*4+2]);scene.add(gateObj);
function setFrame(f){{const thr=THRS[f]||0;let visible=0;for(let i=0;i<M;i++){{const w=raw[i*4+3];if(w<=thr){{dummy.position.set(raw[i*4],raw[i*4+1],raw[i*4+2]);dummy.scale.setScalar(voxScale);dummy.updateMatrix();instMesh.setMatrixAt(i,dummy.matrix);visible++;}}else{{dummy.position.set(0,-999,0);dummy.scale.setScalar(0.001);dummy.updateMatrix();instMesh.setMatrixAt(i,dummy.matrix);}}}}instMesh.instanceMatrix.needsUpdate=true;
const fillPct=(thr*100).toFixed(1);document.getElementById('hFill').textContent=fillPct+'%';document.getElementById('hVox').textContent=visible.toLocaleString();
const t=(f/NF)*(window.FILL_TIME||1.0);document.getElementById('hTime').textContent=t<1?(t*1000).toFixed(1)+' ms':t.toFixed(3)+' s';
const pct=(f/Math.max(NF-1,1))*100;document.getElementById('progfill').style.width=pct+'%';document.getElementById('progthumb').style.left=pct+'%';document.getElementById('fc').textContent=(f+1)+' / '+NF;}}
function hideAll(){{for(let i=0;i<M;i++){{dummy.position.set(0,-9999,0);dummy.scale.setScalar(0.0001);dummy.updateMatrix();instMesh.setMatrixAt(i,dummy.matrix);}}instMesh.instanceMatrix.needsUpdate=true;document.getElementById('hFill').textContent='0.0%';document.getElementById('hVox').textContent='0';document.getElementById('hTime').textContent='0.000 s';document.getElementById('progfill').style.width='0%';document.getElementById('progthumb').style.left='0%';document.getElementById('fc').textContent='0 / '+NF;}}
hideAll();
let isDrag=false,lastMX=0,lastMY=0;let spherical={{theta:0.8,phi:1.1,r:7.0}};let target=new THREE.Vector3(0,0,0);let panOffset=new THREE.Vector3();
function updateCamera(){{const x=spherical.r*Math.sin(spherical.phi)*Math.sin(spherical.theta);const y=spherical.r*Math.cos(spherical.phi);const z=spherical.r*Math.sin(spherical.phi)*Math.cos(spherical.theta);camera.position.set(target.x+panOffset.x+x,target.y+panOffset.y+y,target.z+panOffset.z+z);const flipped=(spherical.phi%(Math.PI*2))>Math.PI;camera.up.set(0,flipped?-1:1,0);camera.lookAt(target.x+panOffset.x,target.y+panOffset.y,target.z+panOffset.z);}}
updateCamera();
const cvs=renderer.domElement;let isPan=false;
cvs.addEventListener('contextmenu',e=>e.preventDefault());
cvs.addEventListener('mousedown',e=>{{isDrag=true;isPan=(e.button===2||e.button===1||e.shiftKey);lastMX=e.clientX;lastMY=e.clientY;}});
window.addEventListener('mouseup',()=>{{isDrag=false;isPan=false;}});
window.addEventListener('mousemove',e=>{{if(!isDrag)return;const dx=e.clientX-lastMX,dy=e.clientY-lastMY;lastMX=e.clientX;lastMY=e.clientY;if(isPan||e.shiftKey){{const s=spherical.r*0.0015;const viewDir=camera.getWorldDirection(new THREE.Vector3());const worldUp=new THREE.Vector3(0,1,0);const camRight=new THREE.Vector3().crossVectors(viewDir,worldUp).normalize();const camUp=new THREE.Vector3().crossVectors(camRight,viewDir).normalize();panOffset.addScaledVector(camRight,dx*s);panOffset.addScaledVector(camUp,-dy*s);}}else{{spherical.theta-=dx*0.008;spherical.phi+=dy*0.008;}}updateCamera();}});
cvs.addEventListener('wheel',e=>{{e.preventDefault();spherical.r=Math.max(0.5,Math.min(15,spherical.r*(e.deltaY>0?1.08:0.93)));updateCamera();}},{{passive:false}});
let t0x=0,t0y=0,pinchD0=0;
cvs.addEventListener('touchstart',e=>{{if(e.touches.length===1){{t0x=e.touches[0].clientX;t0y=e.touches[0].clientY;}}else if(e.touches.length===2){{const dx=e.touches[0].clientX-e.touches[1].clientX;const dy=e.touches[0].clientY-e.touches[1].clientY;pinchD0=Math.sqrt(dx*dx+dy*dy);}}e.preventDefault();}},{{passive:false}});
cvs.addEventListener('touchmove',e=>{{if(e.touches.length===1){{spherical.theta-=(e.touches[0].clientX-t0x)*0.010;spherical.phi+=(e.touches[0].clientY-t0y)*0.010;t0x=e.touches[0].clientX;t0y=e.touches[0].clientY;}}else if(e.touches.length===2){{const dx=e.touches[0].clientX-e.touches[1].clientX;const dy=e.touches[0].clientY-e.touches[1].clientY;const d=Math.sqrt(dx*dx+dy*dy);spherical.r=Math.max(0.5,Math.min(15,spherical.r*(pinchD0/d)));pinchD0=d;}}updateCamera();e.preventDefault();}},{{passive:false}});
let curFrame=0,playing=false,autoRot=false,lastTick=0,frameMs=80;
const SPEED_TABLE=[300,200,120,80,50,35,20,12];const SPEED_LABELS=['0.5×','1×','1.5×','2×','3×','4×','6×','8×'];
function onSpeed(v){{const i=parseInt(v)-1;frameMs=SPEED_TABLE[i];document.getElementById('spdlbl').textContent=SPEED_LABELS[i];}}
function togglePlay(){{playing=!playing;const b=document.getElementById('btnPlay');b.textContent=playing?'⏸ Pause':'▶ Play';b.classList.toggle('on',playing);}}
function resetAnim(){{playing=false;curFrame=0;document.getElementById('btnPlay').textContent='▶ Play';document.getElementById('btnPlay').classList.remove('on');hideAll();}}
function toggleAutoRot(){{autoRot=!autoRot;document.getElementById('btnRot').classList.toggle('on',autoRot);}}
function toggleWire(){{if(wireObj){{wireObj.visible=!wireObj.visible;}}document.getElementById('btnWire').classList.toggle('on',wireObj&&wireObj.visible);}}
function toggleSolid(){{if(solidObj){{solidObj.visible=!solidObj.visible;}}document.getElementById('btnSolid').classList.toggle('on',solidObj&&solidObj.visible);}}
const gizmoCanvas=document.getElementById('gizmoCvs');const gCtx=gizmoCanvas.getContext('2d');
const GCX=36,GCY=36,GLEN=26;
const GAXES=[{{label:'X',dir:[1,0,0],col:'#ff5555',negCol:'#551111'}},{{label:'Y',dir:[0,1,0],col:'#55ff55',negCol:'#115511'}},{{label:'Z',dir:[0,0,1],col:'#5599ff',negCol:'#112255'}}];
function drawGizmo(){{gCtx.clearRect(0,0,72,72);const m=camera.matrixWorldInverse;const proj=GAXES.map(ax=>{{const vx=m.elements[0]*ax.dir[0]+m.elements[4]*ax.dir[1]+m.elements[8]*ax.dir[2];const vy=m.elements[1]*ax.dir[0]+m.elements[5]*ax.dir[1]+m.elements[9]*ax.dir[2];const vz=m.elements[2]*ax.dir[0]+m.elements[6]*ax.dir[1]+m.elements[10]*ax.dir[2];return{{label:ax.label,col:ax.col,negCol:ax.negCol,sx:GCX+vx*GLEN,sy:GCY-vy*GLEN,nsx:GCX-vx*GLEN,nsy:GCY+vy*GLEN,depth:vz}};}});proj.sort((a,b)=>a.depth-b.depth);proj.forEach(ax=>{{gCtx.beginPath();gCtx.moveTo(GCX,GCY);gCtx.lineTo(ax.nsx,ax.nsy);gCtx.strokeStyle=ax.negCol;gCtx.lineWidth=1.2;gCtx.setLineDash([3,3]);gCtx.globalAlpha=0.55;gCtx.stroke();gCtx.setLineDash([]);gCtx.globalAlpha=1.0;}});[...proj].reverse().forEach(ax=>{{gCtx.beginPath();gCtx.moveTo(GCX,GCY);gCtx.lineTo(ax.sx,ax.sy);gCtx.strokeStyle=ax.col;gCtx.lineWidth=2.5;gCtx.stroke();const ang=Math.atan2(ax.sy-GCY,ax.sx-GCX);gCtx.beginPath();gCtx.moveTo(ax.sx,ax.sy);gCtx.lineTo(ax.sx-8*Math.cos(ang-0.4),ax.sy-8*Math.sin(ang-0.4));gCtx.lineTo(ax.sx-8*Math.cos(ang+0.4),ax.sy-8*Math.sin(ang+0.4));gCtx.closePath();gCtx.fillStyle=ax.col;gCtx.fill();const lx=ax.sx+(ax.sx-GCX)*0.32,ly=ax.sy+(ax.sy-GCY)*0.32;gCtx.font='bold 11px Courier New';gCtx.fillStyle=ax.col;gCtx.textAlign='center';gCtx.textBaseline='middle';gCtx.fillText(ax.label,lx,ly);}});gCtx.beginPath();gCtx.arc(GCX,GCY,2.5,0,Math.PI*2);gCtx.fillStyle='#ffffff';gCtx.fill();}}
function animate(ts){{requestAnimationFrame(animate);if(autoRot){{spherical.theta+=0.004;updateCamera();}}if(playing&&ts-lastTick>=frameMs){{lastTick=ts;curFrame=(curFrame+1)%NF;setFrame(curFrame);}}renderer.render(scene,camera);drawGizmo();}}
const pw=document.getElementById('progwrap');let pdrag=false;
function seekTo(e){{const rect=pw.getBoundingClientRect();const x=(e.touches?e.touches[0].clientX:e.clientX)-rect.left;curFrame=Math.round(Math.max(0,Math.min(1,x/rect.width))*(NF-1));setFrame(curFrame);}}
pw.addEventListener('mousedown',e=>{{pdrag=true;seekTo(e);}});window.addEventListener('mouseup',()=>pdrag=false);window.addEventListener('mousemove',e=>{{if(pdrag)seekTo(e);}});pw.addEventListener('touchstart',e=>{{pdrag=true;seekTo(e);}},{{passive:true}});
function onResize(){{const w=viewport.clientWidth;const h=viewport.clientHeight;if(w<1||h<1)return;renderer.setSize(w,h);camera.aspect=w/h;camera.updateProjectionMatrix();}}
window.addEventListener('resize',onResize);onResize();requestAnimationFrame(animate);
</script>
</body>
</html>"""
    return html


def build_flow3d_viewer(coords: np.ndarray, weights: np.ndarray,
                        num_frames: int = 30, max_points: int = 8000) -> str:
    N = len(coords)
    if N == 0:
        return "<p>복셀 데이터 없음</p>"

    if N > max_points:
        idx       = np.linspace(0, N - 1, max_points, dtype=int)
        coords_s  = coords[idx]
        weights_s = weights[idx]
    else:
        coords_s  = coords
        weights_s = weights

    c_min    = coords_s.min(axis=0)
    c_max    = coords_s.max(axis=0)
    scale    = float(np.maximum(c_max - c_min, 1e-6).max())
    center   = (c_min + c_max) / 2.0
    coords_n = ((coords_s - center) / scale * 2.0).astype(np.float32)
    thresholds = np.linspace(0.0, 1.0, num_frames + 1)[1:]
    xyzw       = np.column_stack([coords_n, weights_s])
    xyzw_list  = [[round(float(v), 3) for v in row] for row in xyzw]

    import json as _json
    xyzw_json = _json.dumps(xyzw_list)
    thr_json  = _json.dumps([round(float(t), 4) for t in thresholds])
    nf        = num_frames

    # (Canvas 2D fallback viewer — 원본과 동일하게 유지)
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>*{{margin:0;padding:0;box-sizing:border-box}}body{{background:#0a0f1a;font-family:'Courier New',monospace;color:#8ecfff;overflow:hidden}}
#wrap{{position:relative;width:100%;height:100%}}canvas{{display:block;width:100%;cursor:grab}}canvas:active{{cursor:grabbing}}
#hud{{position:absolute;top:10px;left:12px;font-size:11px;background:rgba(0,10,30,.7);border:1px solid #1a3a5c;border-radius:6px;padding:6px 12px;line-height:1.7;pointer-events:none;min-width:170px;}}
#hud .val{{color:#4df0c0;font-weight:bold}}#hud .lbl{{color:#557a99}}
#ctrl{{position:absolute;bottom:0;left:0;right:0;background:rgba(5,12,28,.92);border-top:1px solid #1a3a5c;padding:8px 14px;display:flex;flex-direction:column;gap:6px;}}
.ctrl-row{{display:flex;align-items:center;gap:10px;flex-wrap:wrap}}
#prog-wrap{{flex:1;min-width:120px;position:relative;height:18px;cursor:pointer}}
#prog-bg{{position:absolute;top:50%;transform:translateY(-50%);width:100%;height:4px;background:#1a3a5c;border-radius:2px;}}
#prog-fill{{position:absolute;top:50%;transform:translateY(-50%);width:0%;height:4px;background:linear-gradient(90deg,#0d6efd,#4df0c0);border-radius:2px;transition:width .1s;}}
#prog-thumb{{position:absolute;top:50%;transform:translate(-50%,-50%);width:14px;height:14px;background:#4df0c0;border-radius:50%;left:0%;cursor:grab;box-shadow:0 0 6px #4df0c0;}}
.btn{{background:rgba(13,110,253,.15);border:1px solid #1a3a5c;color:#8ecfff;border-radius:5px;padding:3px 10px;cursor:pointer;font-size:12px;white-space:nowrap;transition:background .15s,border-color .15s;}}
.btn:hover{{background:rgba(77,240,192,.15);border-color:#4df0c0;color:#4df0c0}}.btn.active{{background:rgba(77,240,192,.25);border-color:#4df0c0;color:#4df0c0}}
#spd-wrap{{display:flex;align-items:center;gap:6px;font-size:11px}}#spd{{width:80px;accent-color:#4df0c0;cursor:pointer}}
#fc{{font-size:11px;color:#4df0c0;min-width:55px;text-align:right}}
</style></head><body>
<div id="wrap"><canvas id="c"></canvas>
<div id="hud"><div><span class="lbl">충진률 </span><span class="val" id="h-fill">0.0%</span></div>
<div><span class="lbl">물리시간</span><span class="val" id="h-time">0.000 s</span></div>
<div><span class="lbl">표시복셀</span><span class="val" id="h-vox">0</span></div>
<div style="margin-top:4px;font-size:10px;color:#33556e">좌클릭:회전 | 우클릭·중간:이동 | Shift+드래그:이동 | 스크롤:줌</div></div>
<div id="ctrl">
<div class="ctrl-row"><div id="prog-wrap"><div id="prog-bg"></div><div id="prog-fill"></div><div id="prog-thumb"></div></div><span id="fc">0 / {nf}</span></div>
<div class="ctrl-row">
<button class="btn" id="btn-play" onclick="togglePlay()">▶ Play</button>
<button class="btn" id="btn-reset" onclick="resetAnim()">↩ Reset</button>
<button class="btn" id="btn-rot" onclick="toggleAutoRot()">⟳ Auto Rotate</button>
<div id="spd-wrap"><span style="color:#557a99">Speed</span><input id="spd" type="range" min="1" max="8" value="2" step="1" oninput="onSpeedChange(this.value)"><span id="spd-lbl" style="color:#4df0c0">1×</span></div>
<div style="margin-left:auto;font-size:10px;color:#33556e"><span style="color:#ff4466">●</span> Gate &nbsp;<span style="display:inline-block;width:10px;height:10px;background:linear-gradient(135deg,#0d6efd,#4df0c0);border-radius:2px;vertical-align:middle"></span> Flow</div>
</div></div></div>
<script>
const XYZW={xyzw_json};const THRS={thr_json};const NF={nf};const M=XYZW.length;
const canvas=document.getElementById('c');const ctx=canvas.getContext('2d');let W=0,H=0;
function resize(){{const wrap=document.getElementById('wrap');W=wrap.clientWidth||640;H=Math.max(wrap.clientHeight-72,200);canvas.width=W;canvas.height=H;draw();}}
window.addEventListener('resize',resize);
let rotX=0.4,rotY=-0.6,zoom=1.0,panX=0,panY=0;let autoRot=false,autoRotSpeed=0.005;
function project(x,y,z){{let x1=x*Math.cos(rotY)+z*Math.sin(rotY);let z1=-x*Math.sin(rotY)+z*Math.cos(rotY);let y2=y*Math.cos(rotX)-z1*Math.sin(rotX);let z2=y*Math.sin(rotX)+z1*Math.cos(rotX);const fov=3.0*zoom;const dz=4.0+z2;if(dz<0.01)return null;return[W/2+panX+(x1*fov/dz)*W*0.38,H/2+panY-(y2*fov/dz)*W*0.38];}}
let curFrame=0,playing=false,lastTick=0,frameMs=120;const SPEED_TABLE=[240,120,80,60,40,30,20,15];
function onSpeedChange(v){{const idx=parseInt(v)-1;frameMs=SPEED_TABLE[idx];const labels=['0.5×','1×','1.5×','2×','3×','4×','6×','8×'];document.getElementById('spd-lbl').textContent=labels[idx];}}
function togglePlay(){{playing=!playing;const btn=document.getElementById('btn-play');btn.textContent=playing?'⏸ Pause':'▶ Play';btn.classList.toggle('active',playing);if(playing)requestAnimationFrame(animLoop);}}
function resetAnim(){{playing=false;document.getElementById('btn-play').textContent='▶ Play';document.getElementById('btn-play').classList.remove('active');curFrame=0;updateUI();draw();}}
function toggleAutoRot(){{autoRot=!autoRot;document.getElementById('btn-rot').classList.toggle('active',autoRot);if(autoRot||playing)requestAnimationFrame(animLoop);}}
function animLoop(ts){{if(autoRot){{rotY+=autoRotSpeed;draw();}}if(playing){{if(ts-lastTick>=frameMs){{lastTick=ts;if(curFrame<NF-1){{curFrame++;}}else{{curFrame=0;}}updateUI();draw();}}}};if(playing||autoRot)requestAnimationFrame(animLoop);}}
function updateUI(){{const thr=THRS[curFrame]||0;const fill=(thr*100).toFixed(1);const voxCount=XYZW.filter(p=>p[3]<=thr).length;document.getElementById('h-fill').textContent=fill+'%';document.getElementById('h-vox').textContent=voxCount.toLocaleString();const t=(curFrame/NF)*(window.FILL_TIME||1.0);document.getElementById('h-time').textContent=t<1?(t*1000).toFixed(1)+' ms':t.toFixed(3)+' s';const pct=(curFrame/(NF-1))*100;document.getElementById('prog-fill').style.width=pct+'%';document.getElementById('prog-thumb').style.left=pct+'%';document.getElementById('fc').textContent=(curFrame+1)+' / '+NF;}}
function draw(){{ctx.clearRect(0,0,W,H);const bg=ctx.createRadialGradient(W/2,H/2,0,W/2,H/2,Math.max(W,H)*0.8);bg.addColorStop(0,'#0d1829');bg.addColorStop(1,'#060c18');ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);ctx.strokeStyle='rgba(20,60,100,0.5)';ctx.lineWidth=0.5;for(let g=-5;g<=5;g++){{const step=0.22;const a=project(g*step,-1.1,-1);const b=project(g*step,-1.1,1);const c=project(-1,-1.1,g*step);const d=project(1,-1.1,g*step);if(a&&b){{ctx.beginPath();ctx.moveTo(a[0],a[1]);ctx.lineTo(b[0],b[1]);ctx.stroke();}}if(c&&d){{ctx.beginPath();ctx.moveTo(c[0],c[1]);ctx.lineTo(d[0],d[1]);ctx.stroke();}}}};const thr=THRS[curFrame]||0;const pts=[];for(let i=0;i<M;i++){{const p=XYZW[i];if(p[3]>thr)continue;const proj=project(p[0],p[1],p[2]);if(!proj)continue;pts.push({{sx:proj[0],sy:proj[1],w:p[3]}});}};pts.sort((a,b)=>b.w-a.w);for(const pt of pts){{const t=thr>0?pt.w/thr:0;const r=Math.round(10+t*30);const g=Math.round(80+t*170);const b=Math.round(180+t*75);const alpha=0.55+t*0.35;ctx.fillStyle=`rgba(${{r}},${{g}},${{b}},${{alpha}})`;ctx.beginPath();ctx.arc(pt.sx,pt.sy,3,0,Math.PI*2);ctx.fill();}};const gateIdx=XYZW.reduce((bi,p,i)=>p[3]<XYZW[bi][3]?i:bi,0);const gp=project(XYZW[gateIdx][0],XYZW[gateIdx][1],XYZW[gateIdx][2]);if(gp){{const grd=ctx.createRadialGradient(gp[0],gp[1],0,gp[0],gp[1],14);grd.addColorStop(0,'rgba(255,60,80,0.6)');grd.addColorStop(1,'rgba(255,60,80,0)');ctx.fillStyle=grd;ctx.beginPath();ctx.arc(gp[0],gp[1],14,0,Math.PI*2);ctx.fill();ctx.fillStyle='#ff4466';ctx.beginPath();ctx.arc(gp[0],gp[1],5,0,Math.PI*2);ctx.fill();ctx.strokeStyle='#fff';ctx.lineWidth=1.2;ctx.beginPath();ctx.arc(gp[0],gp[1],5,0,Math.PI*2);ctx.stroke();}};const axO=project(0,0,0);[[0.18,0,0,'#ef4444','X'],[0,0.18,0,'#22c55e','Y'],[0,0,0.18,'#3b82f6','Z']].forEach(([ax,ay,az,col,lbl])=>{{const ep=project(ax,ay,az);if(!axO||!ep)return;ctx.strokeStyle=col;ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(axO[0],axO[1]);ctx.lineTo(ep[0],ep[1]);ctx.stroke();ctx.fillStyle=col;ctx.font='bold 10px Courier New';ctx.fillText(lbl,ep[0]+3,ep[1]-3);}});}}
const progWrap=document.getElementById('prog-wrap');let progDrag=false;
function seekTo(e){{const rect=progWrap.getBoundingClientRect();const x=(e.touches?e.touches[0].clientX:e.clientX)-rect.left;const ratio=Math.max(0,Math.min(1,x/rect.width));curFrame=Math.round(ratio*(NF-1));updateUI();draw();}}
progWrap.addEventListener('mousedown',e=>{{progDrag=true;seekTo(e);}});window.addEventListener('mouseup',()=>progDrag=false);window.addEventListener('mousemove',e=>{{if(progDrag)seekTo(e);}});progWrap.addEventListener('touchstart',e=>{{progDrag=true;seekTo(e);}},{{passive:true}});window.addEventListener('touchend',()=>progDrag=false);window.addEventListener('touchmove',e=>{{if(progDrag)seekTo(e);}},{{passive:true}});
let drag=false,panDrag=false,lastX=0,lastY=0;canvas.addEventListener('contextmenu',e=>e.preventDefault());canvas.addEventListener('mousedown',e=>{{lastX=e.clientX;lastY=e.clientY;if(e.button===2||e.button===1){{panDrag=true;}}else{{drag=true;}}}});window.addEventListener('mouseup',()=>{{drag=false;panDrag=false;}});window.addEventListener('mousemove',e=>{{const dx=e.clientX-lastX,dy=e.clientY-lastY;lastX=e.clientX;lastY=e.clientY;if(panDrag||(drag&&e.shiftKey)){{panX+=dx;panY+=dy;draw();}}else if(drag){{rotY+=dx*.013;rotX+=dy*.013;rotX=Math.max(-Math.PI/2,Math.min(Math.PI/2,rotX));draw();}}}});canvas.addEventListener('wheel',e=>{{e.preventDefault();zoom*=e.deltaY>0?0.92:1.09;zoom=Math.max(0.15,Math.min(10,zoom));draw();}},{{passive:false}});
let t0x=0,t0y=0,pinchD0=0;canvas.addEventListener('touchstart',e=>{{if(e.touches.length===1){{t0x=e.touches[0].clientX;t0y=e.touches[0].clientY;}}else if(e.touches.length===2){{const dx=e.touches[0].clientX-e.touches[1].clientX;const dy=e.touches[0].clientY-e.touches[1].clientY;pinchD0=Math.sqrt(dx*dx+dy*dy);}}e.preventDefault();}},{{passive:false}});canvas.addEventListener('touchmove',e=>{{if(e.touches.length===1){{rotY+=(e.touches[0].clientX-t0x)*.013;rotX+=(e.touches[0].clientY-t0y)*.013;t0x=e.touches[0].clientX;t0y=e.touches[0].clientY;}}else if(e.touches.length===2){{const dx=e.touches[0].clientX-e.touches[1].clientX;const dy=e.touches[0].clientY-e.touches[1].clientY;const d=Math.sqrt(dx*dx+dy*dy);zoom*=d/pinchD0;zoom=Math.max(0.15,Math.min(10,zoom));pinchD0=d;}}draw();e.preventDefault();}},{{passive:false}});
resize();updateUI();
</script></body></html>"""
    return html


# ═══════════════════════════════════════════════════════════
# UI — 탭 구조
# ═══════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4, tab_phase1, tab_phase2, tab_phase3 = st.tabs([
    "Simulation", "Material Library", "Results", "Settings",
    "🔴 압력·웰드·에어트랩",   # Phase 1 (Day 1~3)
    "🌡 온도·냉각",            # Phase 2 (Day 4~5)
    "📐 수축·변형",            # Phase 3 (Day 6~7)
])

# ═══════════════════════════════════════════════════════════
# TAB 1: SIMULATION
# ═══════════════════════════════════════════════════════════
with tab1:
    st.header("Simulation Setup")
    col1, col2 = st.columns([1, 1], gap="large")

    # ── 왼쪽: STL 업로드 및 3D 시각화 ──
    with col1:
        st.subheader("1️⃣ Part Upload")
        uploaded_file = st.file_uploader("STL 파일 선택", type=["stl"])

        if not uploaded_file:
            default_stl_path = "/app/input/part.stl"
            if os.path.exists(default_stl_path):
                if st.session_state.get("loaded_file_id") != "default_part.stl":
                    try:
                        mesh = trimesh.load(default_stl_path, force='mesh')
                        if isinstance(mesh, trimesh.base.Trimesh) and len(mesh.faces) > 0:
                            st.session_state.mesh = mesh
                            st.session_state.loaded_file_id = "default_part.stl"
                            st.session_state.gate_suggestions = []
                            st.session_state.gate_ai_advice = ""
                            st.success("✅ 기본 STL 파일(input/part.stl) 자동 로드됨")
                    except Exception as e:
                        st.error(f"기본 파일 로드 오류: {e}")

        if uploaded_file:
            file_id = uploaded_file.file_id if hasattr(uploaded_file, 'file_id') else uploaded_file.name
            if st.session_state.get("loaded_file_id") != file_id:
                st.session_state.mesh = load_stl_file(uploaded_file)
                st.session_state.loaded_file_id = file_id
                st.session_state.gate_suggestions = []
                st.session_state.gate_ai_advice = ""

        if st.session_state.mesh:
            mesh   = st.session_state.mesh
            bounds = mesh.bounds
            st.session_state.mesh_bounds = bounds

            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                st.metric("Volume", f"{abs(mesh.volume):.1f} mm³")
            with col_info2:
                dims = bounds[1] - bounds[0]
                st.metric("Size (X,Y,Z)", f"{dims[0]:.1f}, {dims[1]:.1f}, {dims[2]:.1f} mm")
            with col_info3:
                st.metric("Faces", f"{len(mesh.faces)}")

            with st.expander("💾 RAM 예측 및 해상도 추천", expanded=False):
                render_ram_advisor(mesh)

            st.subheader("2️⃣ Gate Position & Size")

            if st.button("🎯 게이트 위치 추천", use_container_width=True):
                with st.spinner("게이트 위치 분석 중..."):
                    suggestions = suggest_gate_positions(mesh)
                    st.session_state.gate_suggestions = suggestions
                    ai_advice = get_ai_gate_advice(mesh, st.session_state.material)
                    if ai_advice:
                        st.session_state.gate_ai_advice = ai_advice

            if st.session_state.gate_suggestions:
                st.markdown("**추천 게이트 위치:**")
                for i, sugg in enumerate(st.session_state.gate_suggestions):
                    col_btn, col_info = st.columns([1, 3])
                    with col_btn:
                        if st.button(sugg["label"], key=f"gate_{i}", use_container_width=True):
                            pos = sugg["position"]
                            st.session_state.gate_x = float(pos[0])
                            st.session_state.gate_y = float(pos[1])
                            st.session_state.gate_z = float(pos[2])
                    with col_info:
                        st.caption(f"📍 {sugg['reason']}")

            if st.session_state.gate_ai_advice:
                st.info(f"🤖 **AI 조언:** {st.session_state.gate_ai_advice}")

            st.markdown("**또는 수동으로 설정:**")
            col_gx, col_gy, col_gz = st.columns(3)
            with col_gx:
                st.session_state.gate_x = st.number_input("Gate X (mm)", value=st.session_state.gate_x)
            with col_gy:
                st.session_state.gate_y = st.number_input("Gate Y (mm)", value=st.session_state.gate_y)
            with col_gz:
                st.session_state.gate_z = st.number_input("Gate Z (mm)", value=st.session_state.gate_z)

            st.divider()
            st.markdown("##### 📐 게이트 크기 설정")
            gate_rec = calc_gate_size_recommendation(mesh, st.session_state.material)

            if "error" not in gate_rec:
                with st.expander("📊 공식 기반 추천 게이트 크기 (클릭하여 확인)", expanded=True):
                    st.markdown(f"**공정:** {gate_rec['process']}")
                    rc1, rc2, rc3 = st.columns(3)
                    with rc1:
                        st.metric("추천 두께 (t)", f"{gate_rec['t_gate']} mm", help=gate_rec['formula_t'])
                    with rc2:
                        st.metric("추천 폭 (W)", f"{gate_rec['w_gate']} mm", help=gate_rec['formula_w'])
                    with rc3:
                        st.metric("원형 환산 직경 (d)", f"{gate_rec['d_gate']} mm", help="d = 2×√(W×t/π)")

                    sr_icon = "🔴" if gate_rec['warn_rect'] else "🟢"
                    st.caption(
                        f"{sr_icon} 직사각형 전단율: **{gate_rec['shear_rect']:,} /s** "
                        f"(허용: {gate_rec['shear_limit']:,}/s) &nbsp;|&nbsp; "
                        f"{'🔴' if gate_rec['warn_circ'] else '🟢'} 원형 전단율: **{gate_rec['shear_circ']:,} /s**"
                    )
                    st.caption(f"부품 체적: {gate_rec['vol_mm3']} mm³ | 표면적: {gate_rec['surf_mm2']} mm² | 추정 벽두께: {gate_rec['t_wall_est']} mm")

                    bc1, bc2 = st.columns(2)
                    with bc1:
                        if st.button("✅ 추천값으로 직사각형 게이트 적용", use_container_width=True):
                            st.session_state.gate_shape  = "rectangular"
                            st.session_state.gate_width  = float(gate_rec['w_gate'])
                            st.session_state.gate_height = float(gate_rec['t_gate'])
                            st.session_state.gate_dia    = float(gate_rec['d_gate'])
                            st.rerun()
                    with bc2:
                        if st.button("✅ 추천값으로 원형 게이트 적용", use_container_width=True):
                            st.session_state.gate_shape = "circular"
                            st.session_state.gate_dia   = float(gate_rec['d_gate'])
                            st.rerun()

            gate_shape_opt = {"원형 (Circular)": "circular", "직사각형 (Rectangular)": "rectangular"}
            cur_shape_label = [k for k, v in gate_shape_opt.items() if v == st.session_state.gate_shape][0]
            chosen_label = st.selectbox("게이트 형상", list(gate_shape_opt.keys()),
                                         index=list(gate_shape_opt.keys()).index(cur_shape_label),
                                         key="gate_shape_sel")
            st.session_state.gate_shape = gate_shape_opt[chosen_label]

            if st.session_state.gate_shape == "circular":
                st.session_state.gate_dia = st.number_input(
                    "원형 게이트 직경 (mm)", min_value=0.3, max_value=15.0,
                    value=float(st.session_state.gate_dia), step=0.1,
                    help="최소 0.3 mm / MIM 일반: 0.5~3 mm / 플라스틱: 1~5 mm"
                )
                st.caption(f"단면적: {np.pi*(st.session_state.gate_dia/2)**2:.2f} mm²")
            else:
                gw_col, gh_col = st.columns(2)
                with gw_col:
                    st.session_state.gate_width = st.number_input(
                        "게이트 가로 폭 W (mm)", min_value=0.3, max_value=20.0,
                        value=float(st.session_state.gate_width), step=0.1
                    )
                with gh_col:
                    st.session_state.gate_height = st.number_input(
                        "게이트 세로 두께 t (mm)", min_value=0.3, max_value=10.0,
                        value=float(st.session_state.gate_height), step=0.1
                    )
                gate_area = st.session_state.gate_width * st.session_state.gate_height
                st.caption(f"단면적: {gate_area:.2f} mm² | 원형 환산 직경: {2*np.sqrt(gate_area/np.pi):.2f} mm")

            st.subheader("3D Visualization")
            html_3d = visualize_mesh_with_gate(
                mesh,
                [st.session_state.gate_x, st.session_state.gate_y, st.session_state.gate_z]
            )
            if html_3d:
                components.html(html_3d, height=560, scrolling=False)
        else:
            st.info("💡 STL 파일을 업로드하면 3D 뷰어가 표시됩니다.")

    # ── 오른쪽: 시뮬레이션 파라미터 ──
    with col2:
        st.subheader("3️⃣ Process Parameters")

        materials = list_available_materials()
        material  = st.selectbox(
            "Material", materials,
            index=materials.index(st.session_state.material)
                  if st.session_state.material in materials else 0
        )

        if material != st.session_state.material:
            st.session_state.material = material
            props = get_material_properties(material)
            st.session_state.props   = props
            st.session_state.temp    = props.get("Tmelt",     230.0)
            st.session_state.press   = props.get("press_mpa", 70.0)
            st.session_state.vel_mms = props.get("vel_mms",   80.0)

        if st.session_state.props:
            props = st.session_state.props
            with st.expander("📊 재료 정보"):
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    st.write(f"**점도:** {props.get('nu', 0):.2e} m²/s")
                    st.write(f"**밀도:** {props.get('rho', 0):.0f} kg/m³")
                    st.write(f"**용융점:** {props.get('Tmelt', 0):.1f} °C")
                with col_p2:
                    st.write(f"**금형온도:** {props.get('Tmold', 0):.1f} °C")
                    st.write(f"**권장 압력:** {props.get('press_mpa', 0):.1f} MPa")
                    st.write(f"**권장 속도:** {props.get('vel_mms', 0):.1f} mm/s")

        st.divider()

        st.session_state.temp = st.slider(
            "Melt Temperature (°C)", min_value=150.0, max_value=350.0,
            value=st.session_state.temp, step=1.0
        )
        st.session_state.press = st.slider(
            "Injection Pressure (MPa)", min_value=10.0, max_value=200.0,
            value=st.session_state.press, step=1.0
        )
        st.session_state.vel_mms = st.slider(
            "Injection Velocity (mm/s)", min_value=10.0, max_value=200.0,
            value=st.session_state.vel_mms, step=1.0
        )
        st.session_state.etime = st.slider(
            "Simulation End Time (s)", min_value=0.1, max_value=5.0,
            value=st.session_state.etime, step=0.1
        )

        if "mesh_res_mm" not in st.session_state:
            st.session_state.mesh_res_mm = 1.0
        st.session_state.mesh_res_mm = st.slider(
            "Voxel Resolution (mm) — 낮을수록 정밀하지만 느림",
            min_value=0.02, max_value=3.0,
            value=st.session_state.mesh_res_mm, step=0.02,
            help="0.5mm = 정밀 (메모리 많이 사용) / 1.0mm = 권장 / 2.0mm = 빠름"
        )

        if st.session_state.mesh:
            _m   = st.session_state.mesh
            _res = st.session_state.mesh_res_mm
            _est_v, _est_ram = estimate_ram_gb(_m, _res)
            if _est_ram < 8:
                _ram_icon, _ram_msg = "🟢", "안전"
            elif _est_ram < 14:
                _ram_icon, _ram_msg = "🟡", "주의 — 해상도를 높이는 것(값 크게) 권장"
            else:
                _ram_icon, _ram_msg = "🔴", "위험 — OOM 가능. 해상도를 높이세요"
            st.caption(
                f"{_ram_icon} **{_res:.1f}mm** → 예상 RAM **{_est_ram:.1f} GB** "
                f"| 복셀 수 **{_est_v:,}** | {_ram_msg}"
            )

        # ════════════════════════════════════════════════
        # ★ 신규: Advanced Solver Parameters
        # ════════════════════════════════════════════════
        st.divider()
        with st.expander("⚙️ Advanced Solver Parameters", expanded=False):
            st.markdown("##### 🧱 벽면 마찰 (Wall Friction)")
            st.session_state.wall_friction_k = st.slider(
                "Wall Friction Strength (k)",
                min_value=0.0, max_value=10.0,
                value=float(st.session_state.wall_friction_k),
                step=0.5,
                help=(
                    "Dijkstra 엣지 가중치에 벽면 마찰을 추가합니다.\n\n"
                    "• **0.0** = 마찰 없음 (순수 거리 기반)\n"
                    "• **3.0** = MIM 기본 권장값\n"
                    "• **5.0+** = 얇은 리브·세부 형상 강조\n\n"
                    "값이 클수록 벽 근처 복셀의 유동 저항이 증가해 "
                    "게이트 근처에서 내부로 먼저 채워지는 효과가 나타납니다."
                ),
            )
            # 값 설명 인라인 표시
            wfk = st.session_state.wall_friction_k
            if wfk == 0.0:
                st.caption("💡 마찰 비활성 — 순수 Dijkstra 최단거리만 사용")
            elif wfk <= 2.0:
                st.caption("💡 약한 마찰 — 내부 우선 충전 경향 약간 반영")
            elif wfk <= 4.0:
                st.caption("💡 MIM 권장 범위 — 벽면 점착 효과 적절히 반영")
            elif wfk <= 7.0:
                st.caption("💡 강한 마찰 — 얇은 리브·좁은 채널 모사에 적합")
            else:
                st.caption("⚠️ 매우 강한 마찰 — 수치 발산 가능성. 주의해서 사용하세요.")

            st.markdown("---")
            st.markdown("##### 📉 거리 기반 속도 감쇠 (Flow Decay)")
            st.session_state.flow_decay = st.slider(
                "Flow Decay (k)",
                min_value=0.0, max_value=2.0,
                value=float(st.session_state.flow_decay),
                step=0.1,
                help=(
                    "게이트에서 멀어질수록 유동 속도를 감쇠시키는 후처리 계수입니다.\n\n"
                    "물리적 근거: v = v₀ / (1 + k·d)  →  time ∝ d + k·d²\n\n"
                    "• **0.0** = 감쇠 없음 (선형 충전)\n"
                    "• **0.5** = 기본 권장값\n"
                    "• **1.0** = 강한 감쇠 (원거리 충전 지연 강조)\n\n"
                    "⚠️ 이 값은 **애니메이션 표시용** display_weights에만 적용되며 "
                    "npz에 저장되는 raw Dijkstra 결과에는 영향을 주지 않습니다."
                ),
            )
            fdk = st.session_state.flow_decay
            if fdk == 0.0:
                st.caption("💡 감쇠 비활성 — 균일 속도로 충전 표시")
            elif fdk <= 0.5:
                st.caption("💡 기본 감쇠 — 원거리 충전 지연이 애니메이션에 자연스럽게 반영")
            else:
                st.caption("💡 강한 감쇠 — 원거리 복셀 충전이 애니메이션 후반에 집중")

        st.divider()

        api_ok, api_msg = check_api_connection(ORACLE_API_URL)
        if api_ok:
            st.success("✅ Oracle Cloud API 연결됨")
        else:
            st.warning(
                f"⚠️ Oracle Cloud API 연결 실패: {api_msg}\n\n"
                "Settings 탭에서 API URL/KEY를 확인하세요. "
                "연결 실패 상태에서도 제출은 가능합니다."
            )

        if st.button("🚀 Run Simulation", use_container_width=True, type="primary"):
            if not uploaded_file and not st.session_state.get("mesh"):
                st.error("❌ STL 파일을 먼저 업로드하세요!")
            else:
                with st.spinner("시뮬레이션 제출 중..."):
                    if uploaded_file:
                        stl_bytes = uploaded_file.getbuffer()
                    else:
                        default_stl_path = "/app/input/part.stl"
                        if os.path.exists(default_stl_path):
                            with open(default_stl_path, "rb") as f:
                                stl_bytes = f.read()
                        else:
                            st.error("❌ 업로드된 STL 파일이 없습니다!")
                            stl_bytes = None

                    if stl_bytes:
                        params = {
                            "gate_x":          st.session_state.gate_x,
                            "gate_y":          st.session_state.gate_y,
                            "gate_z":          st.session_state.gate_z,
                            "gate_dia":        st.session_state.gate_dia,
                            "gate_shape":      st.session_state.gate_shape,
                            "gate_width":      (st.session_state.gate_width
                                                if st.session_state.gate_shape == "rectangular"
                                                else st.session_state.gate_dia),
                            "gate_height":     (st.session_state.gate_height
                                                if st.session_state.gate_shape == "rectangular"
                                                else st.session_state.gate_dia),
                            "vel_mms":         st.session_state.vel_mms,
                            "etime":           st.session_state.etime,
                            "num_frames":      15,
                            "mesh_res_mm":     st.session_state.get("mesh_res_mm", 1.0),
                            # ★ 신규 파라미터 전달
                            "wall_friction_k": st.session_state.wall_friction_k,
                            "flow_decay":      st.session_state.flow_decay,
                        }

                        result = submit_simulation(stl_bytes, params)

                        if result:
                            st.session_state.job_id     = result.get("job_id")
                            st.session_state.sim_status = "submitted"
                            st.success(f"✅ 시뮬레이션 제출됨 (Job ID: {st.session_state.job_id})")
                        else:
                            st.error("❌ 시뮬레이션 제출 실패 — API 서버 응답을 확인하세요.")

# ═══════════════════════════════════════════════════════════
# TAB 2: MATERIAL LIBRARY
# ═══════════════════════════════════════════════════════════
with tab2:
    st.header("Material Library")
    materials_db = load_material_db(MATERIAL_FILE)
    st.markdown(f"**총 {len(materials_db)}개 재료 데이터베이스**")
    search = st.text_input("재료 검색", placeholder="예: PA66, CATAMOLD")
    filtered_materials = {k: v for k, v in materials_db.items() if search.upper() in k or not search}

    if filtered_materials:
        df_data = []
        for name, props in filtered_materials.items():
            df_data.append({
                "Material":          name,
                "Viscosity (m²/s)":  f"{props['nu']:.2e}",
                "Density (kg/m³)":   f"{props['rho']:.0f}",
                "Melt Temp (°C)":    f"{props['Tmelt']:.1f}",
                "Mold Temp (°C)":    f"{props['Tmold']:.1f}",
                "Pressure (MPa)":    f"{props['press_mpa']:.1f}",
                "Velocity (mm/s)":   f"{props['vel_mms']:.1f}",
            })
        st.dataframe(df_data, use_container_width=True)
    else:
        st.info("검색 결과가 없습니다.")

# ═══════════════════════════════════════════════════════════
# TAB 3: RESULTS
# ═══════════════════════════════════════════════════════════
with tab3:
    st.header("Simulation Results")

    if not st.session_state.job_id:
        st.info("아직 시뮬레이션을 실행하지 않았습니다.")
    else:
        st.write(f"**Job ID:** `{st.session_state.job_id}`")

        col_refresh, col_status = st.columns([1, 3])
        with col_refresh:
            if st.button("🔄 Refresh"):
                st.rerun()

        with st.spinner("상태 조회 중..."):
            status = get_job_status(st.session_state.job_id)

            if status:
                st.session_state.sim_status = status.get("status", "unknown")
                current_status = st.session_state.sim_status

                if current_status == "completed":
                    st.success("✅ 시뮬레이션 완료")
                elif current_status == "running":
                    progress_val = status.get("progress", 0)
                    st.info(f"⏳ 실행 중... ({progress_val}%)")
                    st.progress(progress_val / 100)
                    st.caption("⏱ 5초마다 자동 갱신됩니다...")
                    time.sleep(5)
                    st.rerun()
                elif current_status == "queued":
                    st.info("📋 대기 중...")
                    time.sleep(3)
                    st.rerun()
                elif current_status in ("failed", "error", "timeout"):
                    error_msg = status.get("error") or "알 수 없는 오류"
                    st.error(f"❌ **시뮬레이션 실패** ({current_status})")
                    st.error(f"오류 내용: {error_msg}")
                    log_lines = status.get("log", [])
                    if log_lines:
                        with st.expander("📋 솔버 로그 (마지막 100줄)", expanded=True):
                            st.code("\n".join(log_lines), language="text")
                    is_oom = any(kw in error_msg for kw in
                                 ["MemoryError", "OOM", "Killed", "killed", "memory", "code -9", "-9"])
                    if is_oom:
                        st.warning(
                            "💡 **RAM 부족 (OOM Killer) 오류가 감지되었습니다.**\n\n"
                            "`exit code -9` = Linux 커널이 메모리 초과로 프로세스를 강제 종료한 것입니다.\n\n"
                            "**해결 방법:** Simulation 탭 → 해상도 슬라이더를 올려 (숫자 크게, 예: 1.0mm → 1.5mm)\n"
                            "슬라이더 아래 🟢 표시가 될 때까지 조정 후 재시도하세요."
                        )
                else:
                    st.warning(f"⚠️ 상태: {current_status}")

                with st.expander("📊 상세 정보"):
                    st.json(status)

                if current_status == "completed":
                    st.divider()
                    st.subheader("🎬 3D Flow Visualization")

                    if ("last_result" not in st.session_state or
                            st.session_state.get("last_result_job") != st.session_state.job_id):
                        with st.spinner("결과 로드 중..."):
                            results = get_results(st.session_state.job_id)
                            if results:
                                st.session_state.last_result     = results
                                st.session_state.last_result_job = st.session_state.job_id

                    results = st.session_state.get("last_result", {})

                    if results:
                        k1, k2, k3, k4 = st.columns(4)
                        k1.metric("충진 시간",
                                  f"{results.get('theo_fill_time', results.get('fill_time_s', '—'))} s")
                        k2.metric("최고 속도",
                                  f"{results.get('max_vel_mms', results.get('max_velocity_mms', '—'))} mm/s")
                        k3.metric("복셀 수",
                                  f"{results.get('num_voxels', results.get('n_voxels', '—')):,}"
                                  if isinstance(results.get('num_voxels', results.get('n_voxels')), int)
                                  else str(results.get('num_voxels', results.get('n_voxels', '—'))))
                        k4.metric("해상도", f"{results.get('res_mm', '—')} mm")

                        # ★ solver 파라미터 요약 표시
                        if results.get("wall_friction_k") is not None:
                            st.caption(
                                f"🧱 Wall Friction k = **{results['wall_friction_k']}** &nbsp;|&nbsp; "
                                f"📉 Flow Decay k = **{results.get('flow_decay', '—')}**"
                            )

                    frame_cache_key = f"frames_{st.session_state.job_id}"
                    frame_err_key   = f"frames_err_{st.session_state.job_id}"

                    if frame_cache_key not in st.session_state:
                        with st.spinner("프레임 이미지 로드 중..."):
                            frames, err = get_frames(st.session_state.job_id)
                            st.session_state[frame_cache_key] = frames
                            st.session_state[frame_err_key]   = err

                    frames    = st.session_state.get(frame_cache_key, [])
                    frame_err = st.session_state.get(frame_err_key, None)

                    if frames:
                        viewer_h  = st.slider("뷰어 높이 (px)", 400, 1000, 700, 50, key="frame_viewer_h")
                        frame_idx = st.slider(
                            f"프레임  (총 {len(frames)}개)",
                            min_value=1, max_value=len(frames),
                            value=st.session_state.get("frame_slider", 1),
                            step=1, key="frame_slider",
                        )
                        img_b64 = frames[frame_idx - 1]
                        st.components.v1.html(
                            f"""<div style="text-align:center;background:#0a0f1a;
                                           padding:8px;border-radius:8px;">
                              <img src="{img_b64}"
                                   style="max-width:100%;max-height:{viewer_h}px;
                                          object-fit:contain;border-radius:6px;" />
                              <div style="color:#4df0c0;font-size:12px;margin-top:4px;
                                          font-family:monospace;">
                                Frame {frame_idx} / {len(frames)}
                              </div>
                            </div>""",
                            height=viewer_h + 50, scrolling=False,
                        )
                        bc1, bc2, bc3 = st.columns(3)
                        with bc1:
                            if st.button("⏮ 처음", use_container_width=True):
                                st.session_state["frame_slider"] = 1
                                st.rerun()
                        with bc2:
                            if st.button("◀ 이전", use_container_width=True, disabled=(frame_idx <= 1)):
                                st.session_state["frame_slider"] = frame_idx - 1
                                st.rerun()
                        with bc3:
                            if st.button("다음 ▶", use_container_width=True, disabled=(frame_idx >= len(frames))):
                                st.session_state["frame_slider"] = frame_idx + 1
                                st.rerun()
                    else:
                        st.warning("⚠️ 프레임 이미지를 서버에서 불러올 수 없습니다.")
                        if frame_err:
                            with st.expander("🔍 오류 상세", expanded=True):
                                st.code(frame_err)
                        st.caption("↩ 재시도하려면 아래 버튼을 누르세요.")
                        if st.button("🔄 프레임 다시 불러오기"):
                            del st.session_state[frame_cache_key]
                            if frame_err_key in st.session_state:
                                del st.session_state[frame_err_key]
                            st.rerun()

                        st.divider()
                        st.markdown("**대체 뷰어: 복셀 3D 인터랙티브**")
                        vc1, vc2, vc3 = st.columns(3)
                        with vc1: n_frames_v = st.slider("프레임 수",  15, 60, 30, 5)
                        with vc2: max_pts    = st.slider("최대 복셀 수", 2000, 15000, 6000, 1000)
                        with vc3: viewer_h_v = st.slider("뷰어 높이 (px)", 400, 900, 580, 50)

                        cache_key = f"voxel_{st.session_state.job_id}"
                        if cache_key not in st.session_state:
                            with st.spinner("복셀 데이터 로드 중..."):
                                coords, weights = get_voxel_data(st.session_state.job_id)
                                st.session_state[cache_key] = (
                                    (coords, weights) if coords is not None else None
                                )

                        voxel_cache = st.session_state.get(cache_key)
                        if voxel_cache is not None:
                            coords, weights = voxel_cache
                            fill_time = results.get("theo_fill_time", results.get("fill_time_s", 1.0))
                            viewer_html = build_flow3d_viewer(coords, weights, num_frames=n_frames_v, max_points=max_pts)
                            viewer_html = viewer_html.replace("window.FILL_TIME || 1.0", f"window.FILL_TIME || {float(fill_time)}")
                            st.components.v1.html(viewer_html, height=viewer_h_v, scrolling=False)
                        else:
                            st.info("복셀 데이터도 없습니다. 서버의 `/api/frames` 또는 `/api/voxels` 엔드포인트를 확인하세요.")

                    st.divider()
                    st.subheader("🧊 3D WebGL 인터랙티브 뷰어")
                    st.caption("STL 형상(wireframe) 위에 복셀이 프레임별로 채워지는 WebGL 뷰어입니다.")

                    wv_col1, wv_col2, wv_col3 = st.columns(3)
                    with wv_col1: wv_frames = st.slider("프레임 수",   10, 30, 15, 5, key="wv_frames")
                    with wv_col2: wv_maxvox = st.slider("최대 복셀 수", 5000, 80000, 30000, 5000, key="wv_maxvox")
                    with wv_col3: wv_h      = st.slider("뷰어 높이 (px)", 400, 900, 640, 50, key="wv_h")

                    wv_cache_key = f"webgl_{st.session_state.job_id}_{wv_frames}_{wv_maxvox}"
                    if wv_cache_key not in st.session_state:
                        with st.spinner("3D WebGL 뷰어 빌드 중 (voxel_data.npz 로드)..."):
                            wv_coords, wv_weights = get_voxel_data(st.session_state.job_id)
                            if wv_coords is not None:
                                stl_mesh = st.session_state.get("mesh", None)
                                wv_html  = build_webgl_flow_viewer(
                                    wv_coords, wv_weights,
                                    mesh_trimesh=stl_mesh,
                                    num_frames=wv_frames, max_voxels=wv_maxvox,
                                    gate_dia_mm=(st.session_state.gate_dia
                                                 if st.session_state.gate_shape == "circular" else None),
                                    gate_width_mm=(st.session_state.gate_width
                                                   if st.session_state.gate_shape == "rectangular" else None),
                                    gate_height_mm=(st.session_state.gate_height
                                                    if st.session_state.gate_shape == "rectangular" else None),
                                )
                                fill_time_val = results.get("theo_fill_time", results.get("fill_time_s", 1.0))
                                wv_html = wv_html.replace(
                                    "window.FILL_TIME || 1.0", f"window.FILL_TIME || {float(fill_time_val)}"
                                )
                                st.session_state[wv_cache_key] = wv_html
                            else:
                                st.session_state[wv_cache_key] = None

                    wv_html_out = st.session_state.get(wv_cache_key)
                    if wv_html_out:
                        st.components.v1.html(wv_html_out, height=wv_h, scrolling=False)
                        if st.button("🔄 3D 뷰어 재생성", key="wv_regen"):
                            del st.session_state[wv_cache_key]
                            st.rerun()
                    else:
                        st.info("복셀 데이터를 불러올 수 없습니다. 서버의 `/api/voxels/{job_id}` 엔드포인트를 확인하세요.")

                    with st.expander("📄 결과 데이터 (JSON)"):
                        if results:
                            st.json(results)
                        else:
                            st.info("결과 JSON 없음")

# ═══════════════════════════════════════════════════════════
# TAB 4: SETTINGS
# ═══════════════════════════════════════════════════════════
with tab4:
    st.header("Settings")
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Oracle Cloud API")
        st.text_input("API URL", value=ORACLE_API_URL, disabled=True)
        st.text_input("API Key", value=ORACLE_API_KEY, disabled=True, type="password")
        if st.button("🔗 Test Connection"):
            check_api_connection.clear()
            ok, msg = check_api_connection(ORACLE_API_URL)
            if ok:
                st.success("✅ 연결 성공!")
            else:
                st.error(f"❌ 연결 실패: {msg}")

    with col2:
        st.subheader("Application Info")
        st.info(
            "**MIM-Ops Pro v3.2**\n\n"
            "Oracle Cloud Edition\n\n"
            "Features:\n"
            "• STL 3D Visualization\n"
            "• AI Gate Position Recommendation\n"
            "• Material Database Integration\n"
            "• Real-time Simulation Monitoring\n"
            "• Wall Friction & Flow Decay Control ★"
        )

# ═══════════════════════════════════════════════════════════
# TAB PHASE 1: 압력·웰드·에어트랩
# ═══════════════════════════════════════════════════════════
with tab_phase1:
    st.header("🔴 압력 분포 / 웰드라인 / 에어트랩")

    if not st.session_state.get("job_id"):
        st.info("먼저 [Simulation] 탭에서 시뮬레이션을 실행하세요.")
        st.stop()

    job_id    = st.session_state.job_id
    cache_key = f"voxel_full_{job_id}"

    if cache_key not in st.session_state:
        with st.spinner("해석 데이터 로드 중..."):
            st.session_state[cache_key] = get_voxel_data_full(job_id)

    vdata = st.session_state.get(cache_key)

    # ── 압력 분포 섹션 ──
    st.subheader("🔴 압력 분포")
    st.caption("게이트(최고압) → 유동선단(0압) / BFS 가중치 역산")

    if vdata is not None and "pressure" in vdata:
        pressure_arr = vdata["pressure"]
        coords_arr   = vdata["coords"]

        col1, col2, col3 = st.columns(3)
        col1.metric("최대 압력", f"{pressure_arr.max():.1f} MPa")
        col2.metric("평균 압력", f"{pressure_arr.mean():.1f} MPa")
        col3.metric("최소 압력", f"{pressure_arr.min():.1f} MPa")

        p_norm   = (pressure_arr - pressure_arr.min()) / (
            pressure_arr.max() - pressure_arr.min() + 1e-6
        )
        p_height = st.slider("뷰어 높이", 400, 900, 600, 50, key="p1_h")
        html_p   = build_webgl_pressure_viewer(
            coords_arr, p_norm, max_points=10000, mode="pressure"
        )
        components.html(html_p, height=p_height, scrolling=False)

        import plotly.express as px
        st.subheader("압력 분포 히스토그램")
        fig = px.histogram(
            x=pressure_arr, nbins=30,
            labels={"x": "압력 (MPa)", "y": "복셀 수"},
            color_discrete_sequence=["#4488ff"]
        )
        fig.update_layout(paper_bgcolor="#07101f", plot_bgcolor="#0d1a2e",
                          font_color="#8ecfff")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("압력 데이터 없음. 시뮬레이션을 재실행하세요 (Day 1 solver 필요).")

    # ── 웰드라인 섹션 ──
    st.divider()
    st.subheader("🟡 웰드라인")
    st.caption("서로 반대 방향 유동이 만나는 지점 — 강도 취약 위험 구간")

    if vdata is not None and "weld" in vdata:
        weld_arr  = vdata["weld"].astype(bool)
        weld_cnt  = int(weld_arr.sum())
        total_cnt = len(weld_arr)
        weld_pct  = weld_cnt / max(total_cnt, 1) * 100

        col1, col2 = st.columns(2)
        col1.metric("웰드라인 복셀 수", f"{weld_cnt:,}")
        col2.metric("전체 대비 비율",   f"{weld_pct:.2f}%")

        if weld_cnt > 0:
            weld_coords = coords_arr[weld_arr]
            import plotly.graph_objects as go
            non_weld = coords_arr[~weld_arr][::max(1, int((total_cnt - weld_cnt) / 3000))]
            fig = go.Figure()
            fig.add_trace(go.Scatter3d(
                x=non_weld[:, 0], y=non_weld[:, 1], z=non_weld[:, 2],
                mode='markers',
                marker=dict(size=1.5, color='#1a4a7a', opacity=0.3),
                name='일반 복셀'
            ))
            fig.add_trace(go.Scatter3d(
                x=weld_coords[:, 0], y=weld_coords[:, 1], z=weld_coords[:, 2],
                mode='markers',
                marker=dict(size=3.5, color='#ffdd00', opacity=0.9),
                name='웰드라인'
            ))
            fig.update_layout(
                scene=dict(bgcolor='#07101f'),
                paper_bgcolor='#07101f', font_color='#8ecfff',
                margin=dict(l=0, r=0, b=0, t=0), height=500,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.success("✅ 웰드라인 없음 (양호)")
    else:
        st.warning("웰드라인 데이터 없음. Day 2 solver로 시뮬레이션을 재실행하세요.")

    # ── 에어트랩 섹션 (Day 3) — build_webgl_pressure_viewer() 재사용 ──
    st.divider()
    st.subheader("🔵 에어트랩 + 벤트 추천")
    st.caption("충전 말기에 공기가 갇히는 위험 구간 — 표면 근처 + 충전 늦은 복셀")

    if vdata is not None and "airtrap" in vdata:
        at_arr = vdata["airtrap"].astype(bool)
        at_cnt = int(at_arr.sum())

        col1, col2 = st.columns(2)
        col1.metric("에어트랩 복셀", f"{at_cnt:,}")
        col2.metric("위험도", "⚠️ 높음" if at_cnt > 50 else "✅ 낮음")

        # 벤트 추천 위치 (results.json에서)
        last_result = st.session_state.get("last_result", {})
        vent_pos    = last_result.get("results", {}).get("vent_positions", [])

        if vent_pos:
            st.markdown("**📍 추천 벤트 위치:**")
            for i, v in enumerate(vent_pos):
                st.markdown(
                    f"- 벤트 {i+1}: X={v[0]:.2f} mm, Y={v[1]:.2f} mm, Z={v[2]:.2f} mm"
                )

        if at_cnt > 0:
            # build_webgl_pressure_viewer() 재사용 — mode="airtrap"
            # pressure_norm 자리에 복셀 타입: 표면복셀=0.0, 에어트랩=1.0
            at_coords = coords_arr[at_arr]
            non_at    = coords_arr[~at_arr]

            MAX_AT  = 4000
            MAX_NON = 4000
            if len(at_coords) > MAX_AT:
                idx_at    = np.linspace(0, len(at_coords)-1, MAX_AT, dtype=int)
                at_coords = at_coords[idx_at]
            if len(non_at) > MAX_NON:
                idx_non = np.linspace(0, len(non_at)-1, MAX_NON, dtype=int)
                non_at  = non_at[idx_non]

            at_combined_coords = np.vstack([non_at, at_coords])
            at_combined_types  = np.concatenate([
                np.zeros(len(non_at),    dtype=np.float32),   # 표면복셀 = 0.0
                np.ones( len(at_coords), dtype=np.float32),   # 에어트랩 = 1.0
            ])
            vent_arr = np.array(vent_pos, dtype=np.float32) if vent_pos else None

            at_height = st.slider("뷰어 높이", 400, 900, 550, 50, key="at_h")
            html_at = build_webgl_pressure_viewer(
                at_combined_coords,
                at_combined_types,
                max_points=len(at_combined_coords),  # 이미 샘플링 완료
                mode="airtrap",
                vent_coords=vent_arr,
            )
            components.html(html_at, height=at_height, scrolling=False)
        else:
            st.success("✅ 에어트랩 없음 (양호)")
    else:
        st.warning("에어트랩 데이터 없음. Day 3 solver로 시뮬레이션을 재실행하세요.")

# ═══════════════════════════════════════════════════════════
# TAB PHASE 2: 온도·냉각 (Day 4~5에 구현)
# ═══════════════════════════════════════════════════════════
with tab_phase2:
    st.header("🌡 온도 분포 / 냉각 해석")
    st.info("Day 4~5 작업 후 활성화됩니다.")

# ═══════════════════════════════════════════════════════════
# TAB PHASE 3: 수축·변형 (Day 6~7에 구현)
# ═══════════════════════════════════════════════════════════
with tab_phase3:
    st.header("📐 수축률 / 변형 예측")
    st.info("Day 6~7 작업 후 활성화됩니다.")

# ── Footer ──
st.divider()
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "<small>MIM-Ops Pro v3.2 | Oracle Cloud Edition | © 2024</small>"
    "</div>",
    unsafe_allow_html=True
)
