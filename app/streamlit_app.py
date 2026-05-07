"""
🔬 MIM-Ops Pro v3.2 — Oracle Cloud Edition (Advanced GUI)
==========================================================
Oracle Cloud API + 고급 기능 (STL 시각화, AI 게이트 추천, 재료 DB 자동 업데이트)

Features:
  ✅ STL 파일 업로드 및 3D 시각화 (Plotly + PyVista)
  ✅ 게이트 위치 자동 추천 (기하학 분석 + Gemini AI)
  ✅ 재료 데이터베이스 자동 로드 (material_property.txt)
  ✅ 재료 선택 시 조건값 자동 업데이트
  ✅ Oracle Cloud REST API 연동
  ✅ 시뮬레이션 상태 모니터링
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

# Secrets 로드
try:
    ORACLE_API_URL = st.secrets.get("ORACLE_API_URL", "http://localhost:5000")
    ORACLE_API_KEY = st.secrets.get("API_KEY", "default-key")
    GEMINI_API_KEY = st.secrets.get("GEMINI_API_KEY", "")
except:
    ORACLE_API_URL = "http://localhost:5000"
    ORACLE_API_KEY = "default-key"
    GEMINI_API_KEY = ""

# 재료 DB 파일 경로
MATERIAL_FILE = os.path.join(os.path.dirname(__file__), "material_property.txt")
if not os.path.exists(MATERIAL_FILE):
    MATERIAL_FILE = "material_property.txt"

# ═══════════════════════════════════════════════════════════
# SESSION STATE 초기화
# ═══════════════════════════════════════════════════════════

def init_session_state():
    """초기 상태 설정"""
    if "mesh" not in st.session_state:
        st.session_state.mesh = None
    if "mesh_bounds" not in st.session_state:
        st.session_state.mesh_bounds = None
    
    if "material" not in st.session_state:
        st.session_state.material = "CATAMOLD-304L"
    if "props" not in st.session_state:
        st.session_state.props = {}
    
    if "gate_x" not in st.session_state:
        st.session_state.gate_x = 0.0
    if "gate_y" not in st.session_state:
        st.session_state.gate_y = 0.0
    if "gate_z" not in st.session_state:
        st.session_state.gate_z = 0.0
    if "gate_dia" not in st.session_state:
        st.session_state.gate_dia = 2.0
    
    if "temp" not in st.session_state:
        st.session_state.temp = 230.0
    if "press" not in st.session_state:
        st.session_state.press = 70.0
    if "vel_mms" not in st.session_state:
        st.session_state.vel_mms = 80.0
    if "etime" not in st.session_state:
        st.session_state.etime = 1.0
    
    if "job_id" not in st.session_state:
        st.session_state.job_id = None
    if "sim_status" not in st.session_state:
        st.session_state.sim_status = "idle"
    if "last_result" not in st.session_state:
        st.session_state.last_result = None
    
    if "gate_suggestions" not in st.session_state:
        st.session_state.gate_suggestions = []
    if "gate_ai_advice" not in st.session_state:
        st.session_state.gate_ai_advice = ""

init_session_state()

# ═══════════════════════════════════════════════════════════
# ★ RAM 예측 / 해상도 추천 (Issue #2)
# ═══════════════════════════════════════════════════════════

def estimate_ram_gb(mesh, res_mm: float) -> tuple[int, float]:
    """
    주어진 해상도에서 예상 RAM(GB)과 복셀 수를 반환.
    solver.py 의 estimate_memory_gb() 와 동일한 보정 계수 사용.
    순수 배열(196 bytes) × 3배 Python 런타임 오버헤드 = ~588 bytes/voxel.
    """
    bounds = mesh.bounds
    bb = bounds[1] - bounds[0]
    bb = np.maximum(bb, 1e-6)
    grid_nx = int(np.ceil(bb[0] / res_mm))
    grid_ny = int(np.ceil(bb[1] / res_mm))
    grid_nz = int(np.ceil(bb[2] / res_mm))
    grid_total = grid_nx * grid_ny * grid_nz

    try:
        vol = abs(float(mesh.volume))
        bb_vol = float(bb[0] * bb[1] * bb[2])
        fill_ratio = min(vol / bb_vol, 1.0) if bb_vol > 0 else 0.3
    except Exception:
        fill_ratio = 0.3

    est_voxels = max(int(grid_total * fill_ratio), 1)
    bytes_per_voxel = (12 + 4 + 100 + 80) * 3   # ~588 bytes (보수적 추정)
    est_ram_gb_val = (est_voxels * bytes_per_voxel) / (1024 ** 3)
    return est_voxels, est_ram_gb_val


def render_ram_advisor(mesh):
    """
    STL 로드 후 현재 해상도의 예상 RAM 및 권장 해상도 테이블을 표시.
    """
    current_res = st.session_state.get("mesh_res_mm", 1.0)
    est_v, est_ram = estimate_ram_gb(mesh, current_res)

    # 색상 경고
    if est_ram < 8:
        ram_color = "🟢"
    elif est_ram < 14:
        ram_color = "🟡"
    else:
        ram_color = "🔴"

    st.markdown(f"**{ram_color} 현재 해상도 {current_res:.1f}mm → 예상 RAM: `{est_ram:.1f} GB`  |  복셀 수: `{est_v:,}`**")

    # 해상도별 테이블
    rows = []
    for res_test in [0.3, 0.5, 0.8, 1.0, 1.5, 2.0]:
        _, ram_test = estimate_ram_gb(mesh, res_test)
        if ram_test <= 12:
            status = "✅ 16GB 이하"
        elif ram_test <= 18:
            status = "🟡 16~24GB"
        elif ram_test <= 22:
            status = "⚠️ 24GB 근접"
        else:
            status = "❌ 24GB 초과"
        rows.append({"해상도 (mm)": res_test, "예상 RAM (GB)": f"{ram_test:.1f}", "상태": status})

    st.dataframe(rows, use_container_width=True, hide_index=True)

    # [버그 수정] 권장 해상도: 정밀한 쪽(0.3mm)부터 검사 → RAM 안에 드는 가장 정밀한 값
    rec_16, rec_24 = None, None
    for res_test in [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5, 2.0]:
        _, r = estimate_ram_gb(mesh, res_test)
        if r <= 16 * 0.75 and rec_16 is None:
            rec_16 = res_test
        if r <= 24 * 0.75 and rec_24 is None:
            rec_24 = res_test

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        if rec_16:
            if st.button(f"💡 16GB 권장값 적용: {rec_16:.1f}mm", use_container_width=True):
                st.session_state.mesh_res_mm = float(rec_16)
                st.rerun()
    with col_r2:
        if rec_24:
            if st.button(f"💡 24GB 권장값 적용: {rec_24:.1f}mm", use_container_width=True):
                st.session_state.mesh_res_mm = float(rec_24)
                st.rerun()


# ═══════════════════════════════════════════════════════════
# 재료 데이터베이스 함수들
# ═══════════════════════════════════════════════════════════

@st.cache_data(ttl=60)
def load_material_db(filepath: str) -> dict:
    """재료 데이터베이스 로드"""
    db = {}
    
    # 기본값
    default_materials = {
        "CATAMOLD-304L": {"nu": 4.0e-3, "rho": 7900.0, "Tmelt": 185.0, "Tmold": 40.0, "press_mpa": 110.0, "vel_mms": 25.0},
        "WAXBASE-304L": {"nu": 4.0e-3, "rho": 7900.0, "Tmelt": 170.0, "Tmold": 35.0, "press_mpa": 100.0, "vel_mms": 30.0},
        "PA66+GF30": {"nu": 4.0e-4, "rho": 1300.0, "Tmelt": 285.0, "Tmold": 85.0, "press_mpa": 110.0, "vel_mms": 80.0},
        "PP": {"nu": 2.0e-4, "rho": 910.0, "Tmelt": 230.0, "Tmold": 40.0, "press_mpa": 70.0, "vel_mms": 130.0},
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
                        "nu": float(parts[1]),
                        "rho": float(parts[2]),
                        "Tmelt": float(parts[3]),
                        "Tmold": float(parts[4]),
                        "press_mpa": float(parts[5]),
                        "vel_mms": float(parts[6]),
                    }
                except (ValueError, IndexError):
                    continue
    except Exception as e:
        st.warning(f"재료 DB 로드 오류: {e}")
        return default_materials
    
    return db if db else default_materials

def get_material_properties(material_name: str) -> dict:
    """특정 재료의 속성 조회"""
    db = load_material_db(MATERIAL_FILE)
    name_upper = material_name.upper().strip()
    
    if name_upper in db:
        return {**db[name_upper], "material": name_upper, "source": "정확한 일치"}
    
    # 부분 일치 찾기
    candidates = [k for k in db if name_upper in k or k in name_upper]
    if candidates:
        best = candidates[0]
        return {**db[best], "material": best, "source": f"부분 일치: {best}"}
    
    # 기본값 반환
    return {
        "nu": 1e-3, "rho": 1000.0, "Tmelt": 220.0, "Tmold": 50.0,
        "press_mpa": 70.0, "vel_mms": 80.0,
        "material": material_name, "source": "기본값 (DB에 없음)"
    }

def list_available_materials() -> list:
    """사용 가능한 재료 목록"""
    db = load_material_db(MATERIAL_FILE)
    return sorted(db.keys())

# ═══════════════════════════════════════════════════════════
# 3D 시각화 함수들
# ═══════════════════════════════════════════════════════════

def load_stl_file(uploaded_file):
    """STL 파일 로드"""
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp:
            tmp.write(uploaded_file.getbuffer())
            tmp_path = tmp.name

        # force='mesh' 로 항상 Trimesh 반환 시도
        mesh = trimesh.load(tmp_path, force='mesh')

        if isinstance(mesh, trimesh.base.Trimesh) and len(mesh.faces) > 0:
            return mesh

        # force='mesh' 실패 시 Scene 처리
        loaded = trimesh.load(tmp_path)
        if isinstance(loaded, trimesh.base.Trimesh) and len(loaded.faces) > 0:
            return loaded
        elif hasattr(loaded, 'geometry') and loaded.geometry:
            # Scene → geometry dict의 values()가 Trimesh 객체들
            geom_list = [g for g in loaded.geometry.values()
                         if isinstance(g, trimesh.base.Trimesh) and len(g.faces) > 0]
            if geom_list:
                return trimesh.util.concatenate(geom_list)

        st.error("STL 파일에서 메시를 읽을 수 없습니다. 파일을 확인하세요.")
        return None
    except Exception as e:
        st.error(f"STL 로드 오류: {e}")
        return None

def visualize_mesh_with_gate(mesh: trimesh.Trimesh, gate_pos: list = None):
    """
    순수 Python → Canvas 2D 소프트웨어 렌더러 기반 3D 시각화.
    외부 CDN 의존성 없음 — Docker 오프라인/iframe 환경에서도 100% 작동.
    """
    try:
        vertices = mesh.vertices.copy()
        faces = mesh.faces.copy()

        if len(vertices) == 0 or len(faces) == 0:
            st.error("메시 데이터가 비어 있습니다.")
            return None

        # ── 정규화: 중심 = 0, 최대 치수 = 2 ──────────────
        bounds = mesh.bounds
        center = (bounds[0] + bounds[1]) / 2.0
        scale  = float(np.max(bounds[1] - bounds[0]))
        if scale < 1e-9:
            scale = 1.0

        vn = ((vertices - center) / scale * 2.0)  # [-1, 1] 범위

        # ── 다운샘플 (최대 8000 삼각형 — JS 배열 크기 제한 고려) ──
        MAX_FACES = 8000
        if len(faces) > MAX_FACES:
            idx = np.random.choice(len(faces), MAX_FACES, replace=False)
            faces_ds = faces[idx]
        else:
            faces_ds = faces

        # ── 삼각형별 법선 계산 (face normal → 음영) ──────
        v0 = vn[faces_ds[:, 0]]
        v1 = vn[faces_ds[:, 1]]
        v2 = vn[faces_ds[:, 2]]
        normals = np.cross(v1 - v0, v2 - v0)
        nlen = np.linalg.norm(normals, axis=1, keepdims=True)
        nlen[nlen < 1e-9] = 1.0
        normals /= nlen

        light = np.array([0.6, 0.8, 1.0])
        light /= np.linalg.norm(light)
        brightness = np.clip(np.dot(normals, light), 0.1, 1.0)  # [0.1, 1.0]

        # ── 삼각형 중심 Z값 (페인터 알고리즘 정렬용) ─────
        tri_centers = (v0 + v1 + v2) / 3.0
        z_order = np.argsort(tri_centers[:, 2])  # 가까운 것 나중에 그림

        # ── Gate 정규화 좌표 ──────────────────────────────
        has_gate = gate_pos and len(gate_pos) == 3
        if has_gate:
            gn = ((np.array(gate_pos, dtype=float) - center) / scale * 2.0).tolist()
        else:
            gn = [0.0, 0.0, 0.0]

        # ── JSON 직렬화 ───────────────────────────────────
        # 각 삼각형: [x0,y0,z0, x1,y1,z1, x2,y2,z2, brightness]
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

        tri_json   = json.dumps(tri_data)
        gate_json  = json.dumps(gn)
        has_gate_js = "true" if has_gate else "false"

        html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ background:#111827; display:flex; flex-direction:column;
       align-items:center; font-family:monospace; color:#9ca3af; }}
#wrap {{ position:relative; width:100%; }}
canvas {{ display:block; width:100%; cursor:grab; }}
canvas:active {{ cursor:grabbing; }}
#hud {{ position:absolute; top:6px; left:8px; font-size:11px;
        background:rgba(0,0,0,.55); padding:3px 8px; border-radius:4px;
        pointer-events:none; }}
#legend {{ position:absolute; bottom:6px; left:8px; font-size:11px;
           background:rgba(0,0,0,.55); padding:3px 8px; border-radius:4px;
           pointer-events:none; }}
#bar {{ width:100%; padding:4px 10px; display:flex; gap:12px;
        background:#1f2937; font-size:11px; align-items:center; }}
button {{ background:#374151; color:#d1d5db; border:none; border-radius:4px;
          padding:2px 10px; cursor:pointer; font-size:11px; }}
button:hover {{ background:#4b5563; }}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="c"></canvas>
  <div id="hud">드래그: 회전 &nbsp;|&nbsp; 스크롤: 줌 &nbsp;|&nbsp; Shift+드래그: 이동</div>
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

// ── Canvas setup ──────────────────────────────────────
const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
let W, H;

function resize() {{
  const wrap = document.getElementById('wrap');
  W = wrap.clientWidth  || 640;
  H = Math.round(W * 0.65);
  canvas.width  = W;
  canvas.height = H;
  draw();
}}
window.addEventListener('resize', resize);

// ── Camera state ──────────────────────────────────────
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

// ── 3D → 2D projection ────────────────────────────────
function project(x, y, z) {{
  // Rotate Y
  let x1 =  x * Math.cos(rotY) + z * Math.sin(rotY);
  let z1 = -x * Math.sin(rotY) + z * Math.cos(rotY);
  // Rotate X
  let y2 =  y * Math.cos(rotX) - z1 * Math.sin(rotX);
  let z2 =  y * Math.sin(rotX) + z1 * Math.cos(rotX);
  // Perspective
  const fov = 2.8 * zoom;
  const d = 3.5 + z2;
  if (d < 0.01) return null;
  const sx = W/2 + panX + (x1 * fov / d) * W * 0.42;
  const sy = H/2 + panY - (y2 * fov / d) * W * 0.42;
  return [sx, sy];
}}

// ── Draw ──────────────────────────────────────────────
function draw() {{
  ctx.clearRect(0, 0, W, H);

  // Background gradient
  const grad = ctx.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, '#0f172a');
  grad.addColorStop(1, '#1e293b');
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, W, H);

  // Grid (simple)
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

  // Triangles
  for (let i = 0; i < N_TRIS; i++) {{
    const t = TRIS[i];
    const p0 = project(t[0], t[1], t[2]);
    const p1 = project(t[3], t[4], t[5]);
    const p2 = project(t[6], t[7], t[8]);
    if (!p0 || !p1 || !p2) continue;

    const b = t[9];  // brightness
    if (wireMode) {{
      ctx.strokeStyle = `rgba(126,200,227,${{0.3 + b * 0.4}})`;
      ctx.lineWidth = 0.4;
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]);
      ctx.lineTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.closePath();
      ctx.stroke();
    }} else {{
      // Face fill — steel blue tinted by brightness
      const r = Math.round(40  + b * 90);
      const g = Math.round(90  + b * 110);
      const bl= Math.round(130 + b * 97);
      ctx.fillStyle   = `rgba(${{r}},${{g}},${{bl}},0.88)`;
      ctx.strokeStyle = `rgba(${{r}},${{g}},${{bl}},0.15)`;
      ctx.lineWidth   = 0.3;
      ctx.beginPath();
      ctx.moveTo(p0[0], p0[1]);
      ctx.lineTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }}
  }}

  // Gate marker
  if (HAS_GATE) {{
    const gp = project(GATE[0], GATE[1], GATE[2]);
    if (gp) {{
      // Glow ring
      ctx.beginPath();
      ctx.arc(gp[0], gp[1], 12, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255,68,68,0.18)';
      ctx.fill();
      // Dot
      ctx.beginPath();
      ctx.arc(gp[0], gp[1], 6, 0, Math.PI * 2);
      ctx.fillStyle = '#ff4444';
      ctx.fill();
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 1.5;
      ctx.stroke();
      // Label
      ctx.fillStyle   = '#ff8888';
      ctx.font        = 'bold 11px monospace';
      ctx.fillText('Gate', gp[0] + 10, gp[1] - 6);
    }}
  }}

  // Axes (X=red, Y=green, Z=blue)
  const axO = project(0,0,0);
  const axX = project(0.15,0,0);
  const axY = project(0,0.15,0);
  const axZ = project(0,0,0.15);
  if (axO && axX) {{ drawAxis(axO, axX, '#ef4444', 'X'); }}
  if (axO && axY) {{ drawAxis(axO, axY, '#22c55e', 'Y'); }}
  if (axO && axZ) {{ drawAxis(axO, axZ, '#3b82f6', 'Z'); }}
}}

function drawAxis(o, a, color, label) {{
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(o[0], o[1]);
  ctx.lineTo(a[0], a[1]);
  ctx.stroke();
  ctx.fillStyle = color;
  ctx.font = 'bold 10px monospace';
  ctx.fillText(label, a[0] + 2, a[1] - 2);
}}

// ── Mouse / Touch controls ─────────────────────────────
let dragging = false, lastX = 0, lastY = 0, shiftDown = false;

canvas.addEventListener('mousedown', e => {{
  dragging = true; lastX = e.clientX; lastY = e.clientY;
  shiftDown = e.shiftKey;
}});
window.addEventListener('mouseup', () => dragging = false);
window.addEventListener('mousemove', e => {{
  if (!dragging) return;
  const dx = e.clientX - lastX;
  const dy = e.clientY - lastY;
  lastX = e.clientX; lastY = e.clientY;
  if (e.shiftKey) {{
    panX += dx; panY += dy;
  }} else {{
    rotY += dx * 0.012;
    rotX += dy * 0.012;
    rotX = Math.max(-Math.PI/2, Math.min(Math.PI/2, rotX));
  }}
  draw();
}});
canvas.addEventListener('wheel', e => {{
  e.preventDefault();
  zoom *= (e.deltaY > 0) ? 0.92 : 1.09;
  zoom = Math.max(0.2, Math.min(8, zoom));
  draw();
}}, {{ passive: false }});

// Touch
let t0x=0, t0y=0, pinchD0=0;
canvas.addEventListener('touchstart', e => {{
  if (e.touches.length === 1) {{
    t0x = e.touches[0].clientX;
    t0y = e.touches[0].clientY;
  }} else if (e.touches.length === 2) {{
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
    t0x = e.touches[0].clientX;
    t0y = e.touches[0].clientY;
  }} else if (e.touches.length === 2) {{
    const dx = e.touches[0].clientX - e.touches[1].clientX;
    const dy = e.touches[0].clientY - e.touches[1].clientY;
    const d  = Math.sqrt(dx*dx + dy*dy);
    zoom *= d / pinchD0;
    zoom = Math.max(0.2, Math.min(8, zoom));
    pinchD0 = d;
  }}
  draw();
  e.preventDefault();
}}, {{passive:false}});

resize();
</script>
</body>
</html>"""
        return html
    except Exception as e:
        st.error(f"3D 시각화 오류: {e}")
        return None

# ═══════════════════════════════════════════════════════════
# 게이트 위치 추천 함수들
# ═══════════════════════════════════════════════════════════

def snap_to_mesh_surface(mesh: trimesh.Trimesh, point: np.ndarray) -> np.ndarray:
    """rtree 없이 메시 표면의 가장 가까운 점 계산 (삼각형 중심 기반)"""
    try:
        # 각 삼각형의 중심점 계산
        triangles = mesh.vertices[mesh.faces]           # (N, 3, 3)
        tri_centers = triangles.mean(axis=1)            # (N, 3)
        # 가장 가까운 삼각형 중심 찾기
        dists = np.linalg.norm(tri_centers - point, axis=1)
        closest_tri_idx = int(np.argmin(dists))
        return tri_centers[closest_tri_idx]
    except Exception:
        return point  # 실패 시 원래 점 반환


def suggest_gate_positions(mesh: trimesh.Trimesh) -> list:
    """게이트 위치 자동 추천 (기하학적 분석, rtree 불필요)"""
    suggestions = []
    
    try:
        bounds = mesh.bounds
        center = mesh.centroid
        dims = bounds[1] - bounds[0]
        
        # 1. Bottom-Center
        pt1 = np.array([center[0], center[1], bounds[0][2]])
        snapped1 = snap_to_mesh_surface(mesh, pt1)
        suggestions.append({
            "label": "Bottom-Center",
            "position": snapped1.tolist(),
            "reason": "균형 잡힌 충전"
        })
        
        # 2. Largest dimension 방향
        axis = int(np.argmax(dims))
        pt2 = center.copy()
        pt2[axis] = bounds[0][axis]
        snapped2 = snap_to_mesh_surface(mesh, pt2)
        axis_label = ["X-Min Side", "Y-Min Side", "Z-Min Side"][axis]
        suggestions.append({
            "label": axis_label,
            "position": snapped2.tolist(),
            "reason": "긴 축 방향 충전"
        })
        
        # 3. Top-Center (균형)
        pt3 = np.array([center[0], center[1], bounds[1][2]])
        snapped3 = snap_to_mesh_surface(mesh, pt3)
        suggestions.append({
            "label": "Top-Center (Balanced)",
            "position": snapped3.tolist(),
            "reason": "상단 중심 충전"
        })
        
    except Exception as e:
        st.warning(f"게이트 추천 오류: {e}")
    
    return suggestions

def get_ai_gate_advice(mesh: trimesh.Trimesh, material_name: str):
    """Gemini AI를 사용한 게이트 위치 조언"""
    if not GEMINI_API_KEY:
        return None
    
    try:
        props = get_material_properties(material_name)
        vol = abs(mesh.volume)
        bounds = mesh.bounds
        dims = bounds[1] - bounds[0]
        
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
            json={
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {
                    "maxOutputTokens": 200,
                    "temperature": 0.3,
                }
            },
            timeout=10
        )
        
        if response.status_code == 200:
            data = response.json()
            advice = (
                data.get("candidates", [{}])[0]
                    .get("content", {})
                    .get("parts", [{}])[0]
                    .get("text", "")
                    .strip()
            )
            return advice if advice else None
    except Exception as e:
        st.warning(f"Gemini AI 조언 조회 오류: {e}")
    
    return None

# ═══════════════════════════════════════════════════════════
# Oracle Cloud API 함수들
# ═══════════════════════════════════════════════════════════

def check_api_connection():
    """Oracle Cloud API 연결 확인"""
    try:
        response = requests.get(
            f"{ORACLE_API_URL}/health",
            timeout=5
        )
        return response.status_code == 200
    except:
        return False

def submit_simulation(stl_file_bytes: bytes, params: dict) -> dict:
    """시뮬레이션 요청 제출"""
    try:
        url = f"{ORACLE_API_URL}/api/simulate"
        headers = {
            "Authorization": f"Bearer {ORACLE_API_KEY}"
        }
        
        files = {
            "stl_file": ("part.stl", stl_file_bytes, "application/octet-stream")
        }
        
        data = {
            "gate_x": params.get("gate_x", 0),
            "gate_y": params.get("gate_y", 0),
            "gate_z": params.get("gate_z", 0),
            "gate_dia": params.get("gate_dia", 2.0),
            "vel_mms": params.get("vel_mms", 80),
            "etime": params.get("etime", 1.0),
            "num_frames": params.get("num_frames", 15),
            "mesh_res_mm": params.get("mesh_res_mm", 0.5),
        }
        
        response = requests.post(
            url,
            headers=headers,
            files=files,
            data=data,
            timeout=30
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
    """작업 상태 조회"""
    try:
        url = f"{ORACLE_API_URL}/api/jobs/{job_id}"
        headers = {
            "Authorization": f"Bearer {ORACLE_API_KEY}"
        }
        
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code in (200, 202):
            return response.json()
        else:
            return None
    except Exception as e:
        st.warning(f"상태 조회 오류: {e}")
        return None

def get_results(job_id: str) -> dict:
    """시뮬레이션 결과 조회"""
    try:
        url = f"{ORACLE_API_URL}/api/results/{job_id}"
        headers = {
            "Authorization": f"Bearer {ORACLE_API_KEY}"
        }
        
        response = requests.get(url, headers=headers, timeout=30)
        
        if response.status_code in (200, 202):
            return response.json()
        else:
            return None
    except Exception as e:
        st.warning(f"결과 조회 오류: {e}")
        return None

# ═══════════════════════════════════════════════════════════
# UI - 탭 구조
# ═══════════════════════════════════════════════════════════

tab1, tab2, tab3, tab4 = st.tabs(["Simulation", "Material Library", "Results", "Settings"])

# ═══════════════════════════════════════════════════════════
# TAB 1: SIMULATION
# ═══════════════════════════════════════════════════════════
with tab1:
    st.header("Simulation Setup")
    
    col1, col2 = st.columns([1, 1], gap="large")
    
    # ─── 왼쪽: STL 업로드 및 3D 시각화 ───
    with col1:
        st.subheader("1️⃣ Part Upload")
        uploaded_file = st.file_uploader("STL 파일 선택", type=["stl"])
        
        # ✅ 기본 part.stl 파일 자동 로드 (업로드 없을 때)
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
        
        # 업로드된 파일 처리 (파일이 바뀔 때만 재로드)
        if uploaded_file:
            file_id = uploaded_file.file_id if hasattr(uploaded_file, 'file_id') else uploaded_file.name
            if st.session_state.get("loaded_file_id") != file_id:
                st.session_state.mesh = load_stl_file(uploaded_file)
                st.session_state.loaded_file_id = file_id
                st.session_state.gate_suggestions = []
                st.session_state.gate_ai_advice = ""

        # ── 메시가 session_state에 있으면 무조건 표시 ──────────────
        if st.session_state.mesh:
            mesh = st.session_state.mesh
            bounds = mesh.bounds
            st.session_state.mesh_bounds = bounds

            # 메시 정보
            col_info1, col_info2, col_info3 = st.columns(3)
            with col_info1:
                st.metric("Volume", f"{abs(mesh.volume):.1f} mm³")
            with col_info2:
                dims = bounds[1] - bounds[0]
                st.metric("Size (X,Y,Z)", f"{dims[0]:.1f}, {dims[1]:.1f}, {dims[2]:.1f} mm")
            with col_info3:
                st.metric("Faces", f"{len(mesh.faces)}")

            # ── RAM 예측 (Issue #2) ──────────────────────────────────
            with st.expander("💾 RAM 예측 및 해상도 추천", expanded=False):
                render_ram_advisor(mesh)

            # 게이트 위치 추천
            st.subheader("2️⃣ Gate Position")

            if st.button("🎯 게이트 위치 추천", use_container_width=True):
                with st.spinner("게이트 위치 분석 중..."):
                    suggestions = suggest_gate_positions(mesh)
                    st.session_state.gate_suggestions = suggestions
                    ai_advice = get_ai_gate_advice(mesh, st.session_state.material)
                    if ai_advice:
                        st.session_state.gate_ai_advice = ai_advice

            # 추천된 게이트 위치 표시
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

            # AI 조언
            if st.session_state.gate_ai_advice:
                st.info(f"🤖 **AI 조언:** {st.session_state.gate_ai_advice}")

            # 수동 게이트 설정
            st.markdown("**또는 수동으로 설정:**")
            col_gx, col_gy, col_gz = st.columns(3)
            with col_gx:
                st.session_state.gate_x = st.number_input("Gate X (mm)", value=st.session_state.gate_x)
            with col_gy:
                st.session_state.gate_y = st.number_input("Gate Y (mm)", value=st.session_state.gate_y)
            with col_gz:
                st.session_state.gate_z = st.number_input("Gate Z (mm)", value=st.session_state.gate_z)

            # ── 3D 시각화 ─────────────────────────────────────────
            st.subheader("3D Visualization")
            html_3d = visualize_mesh_with_gate(
                mesh,
                [st.session_state.gate_x, st.session_state.gate_y, st.session_state.gate_z]
            )
            if html_3d:
                components.html(html_3d, height=520, scrolling=False)
        else:
            st.info("💡 STL 파일을 업로드하면 3D 뷰어가 표시됩니다.")
    
    # ─── 오른쪽: 시뮬레이션 파라미터 ───
    with col2:
        st.subheader("3️⃣ Process Parameters")
        
        # 재료 선택
        materials = list_available_materials()
        material = st.selectbox(
            "Material",
            materials,
            index=materials.index(st.session_state.material) if st.session_state.material in materials else 0
        )
        
        # 재료 선택 시 자동 업데이트
        if material != st.session_state.material:
            st.session_state.material = material
            props = get_material_properties(material)
            st.session_state.props = props
            st.session_state.temp = props.get("Tmelt", 230.0)
            st.session_state.press = props.get("press_mpa", 70.0)
            st.session_state.vel_mms = props.get("vel_mms", 80.0)
        
        # 재료 정보 표시
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
        
        # 프로세스 파라미터
        st.session_state.temp = st.slider(
            "Melt Temperature (°C)",
            min_value=150.0, max_value=350.0,
            value=st.session_state.temp, step=1.0
        )
        
        st.session_state.press = st.slider(
            "Injection Pressure (MPa)",
            min_value=10.0, max_value=200.0,
            value=st.session_state.press, step=1.0
        )
        
        st.session_state.vel_mms = st.slider(
            "Injection Velocity (mm/s)",
            min_value=10.0, max_value=200.0,
            value=st.session_state.vel_mms, step=1.0
        )
        
        st.session_state.gate_dia = st.slider(
            "Gate Diameter (mm)",
            min_value=0.5, max_value=5.0,
            value=st.session_state.gate_dia, step=0.1
        )
        
        st.session_state.etime = st.slider(
            "Simulation End Time (s)",
            min_value=0.1, max_value=5.0,
            value=st.session_state.etime, step=0.1
        )

        if "mesh_res_mm" not in st.session_state:
            st.session_state.mesh_res_mm = 1.0
        st.session_state.mesh_res_mm = st.slider(
            "Voxel Resolution (mm) — 낮을수록 정밀하지만 느림",
            min_value=0.3, max_value=3.0,
            value=st.session_state.mesh_res_mm, step=0.1,
            help="0.5mm = 정밀 (메모리 많이 사용) / 1.0mm = 권장 / 2.0mm = 빠름"
        )

        st.divider()
        
        # API 연결 상태
        api_ok = check_api_connection()
        if api_ok:
            st.success("✅ Oracle Cloud API 연결됨")
        else:
            st.error("❌ Oracle Cloud API 연결 실패")
        
        # 시뮬레이션 실행
        if st.button("🚀 Run Simulation", use_container_width=True, type="primary"):
            if not uploaded_file:
                st.error("❌ STL 파일을 먼저 업로드하세요!")
            elif not api_ok:
                st.error("❌ Oracle Cloud API에 연결할 수 없습니다!")
            else:
                with st.spinner("시뮬레이션 제출 중..."):
                    params = {
                        "gate_x": st.session_state.gate_x,
                        "gate_y": st.session_state.gate_y,
                        "gate_z": st.session_state.gate_z,
                        "gate_dia": st.session_state.gate_dia,
                        "vel_mms": st.session_state.vel_mms,
                        "etime": st.session_state.etime,
                        "num_frames": 15,
                        "mesh_res_mm": st.session_state.get("mesh_res_mm", 1.0),
                    }
                    
                    result = submit_simulation(uploaded_file.getbuffer(), params)
                    
                    if result:
                        st.session_state.job_id = result.get("job_id")
                        st.session_state.sim_status = "submitted"
                        st.success(f"✅ 시뮬레이션 제출됨 (Job ID: {st.session_state.job_id})")
                    else:
                        st.error("❌ 시뮬레이션 제출 실패")

# ═══════════════════════════════════════════════════════════
# TAB 2: MATERIAL LIBRARY
# ═══════════════════════════════════════════════════════════
with tab2:
    st.header("Material Library")
    
    materials_db = load_material_db(MATERIAL_FILE)
    
    st.markdown(f"**총 {len(materials_db)}개 재료 데이터베이스**")
    
    # 검색 기능
    search = st.text_input("재료 검색", placeholder="예: PA66, CATAMOLD")
    
    filtered_materials = {
        k: v for k, v in materials_db.items()
        if search.upper() in k or not search
    }
    
    # 테이블 표시
    if filtered_materials:
        df_data = []
        for name, props in filtered_materials.items():
            df_data.append({
                "Material": name,
                "Viscosity (m²/s)": f"{props['nu']:.2e}",
                "Density (kg/m³)": f"{props['rho']:.0f}",
                "Melt Temp (°C)": f"{props['Tmelt']:.1f}",
                "Mold Temp (°C)": f"{props['Tmold']:.1f}",
                "Pressure (MPa)": f"{props['press_mpa']:.1f}",
                "Velocity (mm/s)": f"{props['vel_mms']:.1f}",
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
        
        # 상태 모니터링
        col_refresh, col_status = st.columns([1, 3])
        with col_refresh:
            if st.button("🔄 Refresh"):
                st.rerun()
        
        with st.spinner("상태 조회 중..."):
            status = get_job_status(st.session_state.job_id)
            
            if status:
                st.session_state.sim_status = status.get("status", "unknown")
                current_status = st.session_state.sim_status
                
                # ── [Issue #3] 상태별 표시 개선 ───────────────────────────
                if current_status == "completed":
                    st.success("✅ 시뮬레이션 완료")

                elif current_status == "running":
                    progress_val = status.get("progress", 0)
                    st.info(f"⏳ 실행 중... ({progress_val}%)")
                    st.progress(progress_val / 100)
                    # [Issue #3] running 상태에서 자동 새로고침 (5초 간격)
                    st.caption("⏱ 5초마다 자동 갱신됩니다...")
                    time.sleep(5)
                    st.rerun()

                elif current_status == "queued":
                    st.info("📋 대기 중...")
                    # queued 상태도 자동 갱신
                    time.sleep(3)
                    st.rerun()

                elif current_status in ("failed", "error", "timeout"):
                    # [Issue #3] 오류 상태에서 오류 메시지를 명확하게 표시
                    error_msg = status.get("error") or "알 수 없는 오류"
                    st.error(f"❌ **시뮬레이션 실패** ({current_status})")
                    st.error(f"오류 내용: {error_msg}")

                    # 로그 전문 표시
                    log_lines = status.get("log", [])
                    if log_lines:
                        with st.expander("📋 솔버 로그 (마지막 100줄)", expanded=True):
                            st.code("\n".join(log_lines), language="text")

                    # RAM 부족 가능성 안내
                    if any(kw in error_msg for kw in ["MemoryError", "OOM", "Killed", "killed", "memory"]):
                        st.warning(
                            "💡 **RAM 부족 오류가 감지되었습니다.**\n\n"
                            "Simulation 탭 → '💾 RAM 예측 및 해상도 추천'에서\n"
                            "더 낮은 해상도(예: 1.0mm 또는 1.5mm)를 적용하고 다시 시도하세요."
                        )
                else:
                    st.warning(f"⚠️ 상태: {current_status}")

                # 상태 세부사항
                with st.expander("📊 상세 정보"):
                    st.json(status)
                
                # 결과 다운로드
                if current_status == "completed":
                    st.divider()
                    st.subheader("Download Results")
                    
                    if st.button("📥 Get Results"):
                        with st.spinner("결과 조회 중..."):
                            results = get_results(st.session_state.job_id)
                            
                            if results:
                                st.session_state.last_result = results
                                st.success("✅ 결과 조회 완료")
                                
                                # 결과 JSON 표시
                                with st.expander("📄 결과 데이터"):
                                    st.json(results)
                            else:
                                st.error("❌ 결과 조회 실패")

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
            if check_api_connection():
                st.success("✅ 연결 성공!")
            else:
                st.error("❌ 연결 실패!")
    
    with col2:
        st.subheader("Application Info")
        st.info(
            "**MIM-Ops Pro v3.2**\n\n"
            "Oracle Cloud Edition\n\n"
            "Features:\n"
            "• STL 3D Visualization\n"
            "• AI Gate Position Recommendation\n"
            "• Material Database Integration\n"
            "• Real-time Simulation Monitoring"
        )

# ═══════════════════════════════════════════════════════════
# FOOTER
# ═══════════════════════════════════════════════════════════
st.divider()
st.markdown(
    "<div style='text-align: center; color: gray;'>"
    "<small>MIM-Ops Pro v3.2 | Oracle Cloud Edition | © 2024</small>"
    "</div>",
    unsafe_allow_html=True
)
