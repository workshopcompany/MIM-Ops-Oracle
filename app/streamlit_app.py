"""
MIM-Ops Pro v3.2 - Oracle Cloud Edition
========================================
✅ STL 파일 시각화
✅ 게이트 위치 자동 추천
✅ 재료 선택 시 자동값 변경
✅ Oracle Cloud API 연동
"""

import streamlit as st
import os
import time
import pandas as pd
import numpy as np
import trimesh
import plotly.graph_objects as go
import requests
from datetime import datetime
import tempfile

st.set_page_config(page_title="MIM-Ops Pro", page_icon="🔬", layout="wide")
st.title("🔬 MIM-Ops Pro v3.2: Oracle Cloud Edition")

# ── Configuration ──
ORACLE_API_URL = st.secrets.get("ORACLE_API_URL", "http://localhost:5000")
ORACLE_API_KEY = st.secrets.get("API_KEY", "default-key-change-in-production")
MATERIAL_FILE = os.path.join(os.path.dirname(__file__), "material_property.txt")

# ───────────────────── Session State ─────────────────────
def _init(k, v):
    if k not in st.session_state:
        st.session_state[k] = v

_init("gx", 0.0)
_init("gy", 0.0)
_init("gz", 0.0)
_init("gsize", 2.0)
_init("temp", 230.0)
_init("press", 70.0)
_init("vel", 80.0)
_init("etime", 1.0)
_init("sim_running", False)
_init("sim_status", "idle")
_init("sim_logs", [])
_init("job_id", None)
_init("mat_name", "CATAMOLD-17-4PH")
_init("machine_ton", 50)
_init("screw_dia_mm", 28.0)
_init("mesh", None)
_init("gate_suggested", False)
_init("current_results", None)
_init("num_frames", 15)
_init("mesh_res_mm", 0.5)

# ───────────────────── Logging ─────────────────────
def add_log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    st.session_state["sim_logs"].append(f"[{ts}] {msg}")
    if len(st.session_state["sim_logs"]) > 100:
        st.session_state["sim_logs"] = st.session_state["sim_logs"][-100:]

def show_logs():
    """로그 표시"""
    log_container = st.container()
    with log_container:
        st.subheader("📋 Simulation Logs")
        log_text = "\n".join(st.session_state["sim_logs"])
        st.code(log_text, language="log")

# ═══════════════════════════════════════════════════════════
#  ★★★ MATERIAL DB ★★★
# ═══════════════════════════════════════════════════════════
@st.cache_data(ttl=10)
def load_material_db(filepath: str) -> dict:
    """재료 데이터베이스 로드"""
    db = {}
    if not os.path.exists(filepath):
        return db
    
    try:
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 7:
                    mat_name = parts[0]
                    db[mat_name] = {
                        'nu': float(parts[1]),
                        'rho': float(parts[2]),
                        'Tmelt': float(parts[3]),
                        'Tmold': float(parts[4]),
                        'press_mpa': float(parts[5]),
                        'vel_mms': float(parts[6])
                    }
    except Exception as e:
        st.warning(f"재료 DB 로드 오류: {e}")
    
    return db

def save_material_to_txt(name: str, props: dict) -> bool:
    """재료 저장"""
    try:
        db = load_material_db(MATERIAL_FILE)
        db[name] = props
        
        os.makedirs(os.path.dirname(MATERIAL_FILE) or '.', exist_ok=True)
        
        with open(MATERIAL_FILE, 'w') as f:
            f.write("# MIM-Ops Material Property Database\n")
            f.write("# Format: MATERIAL_NAME | nu(m²/s) | rho(kg/m³) | Tmelt(°C) | Tmold(°C) | press_mpa | vel_mms\n\n")
            for mat, p in sorted(db.items()):
                line = f"{mat} | {p['nu']:.2e} | {p['rho']:.1f} | {p['Tmelt']:.1f} | {p['Tmold']:.1f} | {p['press_mpa']:.1f} | {p['vel_mms']:.1f}\n"
                f.write(line)
        
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"저장 오류: {e}")
        return False

# ───────────────────── API Client ─────────────────────
class OracleAPIClient:
    """Oracle Cloud API 클라이언트"""
    
    def __init__(self, api_url, api_key):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
    
    def health_check(self):
        """API 서버 헬스 체크"""
        try:
            response = requests.get(
                f"{self.api_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except:
            return False
    
    def submit_simulation(self, stl_file_path, params):
        """시뮬레이션 요청"""
        try:
            with open(stl_file_path, 'rb') as f:
                files = {
                    'stl_file': (os.path.basename(stl_file_path), f)
                }
                data = {
                    'signal_id': params.get('signal_id', 'auto'),
                    'gate_x': params.get('gate_x', 0.0),
                    'gate_y': params.get('gate_y', 0.0),
                    'gate_z': params.get('gate_z', 0.0),
                    'gate_dia': params.get('gate_dia', 2.0),
                    'vel_mms': params.get('vel_mms', 25.0),
                    'etime': params.get('etime', 1.0),
                    'num_frames': params.get('num_frames', 15),
                    'mesh_res_mm': params.get('mesh_res_mm', 0.5),
                    'material': params.get('material', 'CATAMOLD-17-4PH'),
                    'screw_dia': params.get('screw_dia', 28.0),
                }
                
                response = requests.post(
                    f"{self.api_url}/api/simulate",
                    files=files,
                    data=data,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=30
                )
                
                if response.status_code in [200, 202]:
                    return response.json()
                else:
                    return {"error": f"API Error: {response.status_code}"}
        except Exception as e:
            return {"error": f"요청 실패: {str(e)}"}
    
    def get_job_status(self, job_id):
        """작업 상태 조회"""
        try:
            response = requests.get(
                f"{self.api_url}/api/jobs/{job_id}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"상태 코드: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def get_results(self, job_id):
        """결과 다운로드"""
        try:
            response = requests.get(
                f"{self.api_url}/api/results/{job_id}",
                headers=self.headers,
                timeout=30
            )
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"상태 코드: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}

api_client = OracleAPIClient(ORACLE_API_URL, ORACLE_API_KEY)

# ───────────────────── STL 시각화 ─────────────────────
def visualize_stl(mesh_obj):
    """Plotly으로 STL 시각화"""
    if mesh_obj is None:
        st.warning("메쉬를 로드해주세요")
        return
    
    vertices = mesh_obj.vertices
    faces = mesh_obj.faces
    
    fig = go.Figure(data=[go.Mesh3d(
        x=vertices[:, 0],
        y=vertices[:, 1],
        z=vertices[:, 2],
        i=faces[:, 0],
        j=faces[:, 1],
        k=faces[:, 2],
        opacity=0.7,
        color="lightblue",
        showlegend=True,
        name="Part"
    )])
    
    # 게이트 위치 표시
    if st.session_state["gx"] or st.session_state["gy"] or st.session_state["gz"]:
        fig.add_trace(go.Scatter3d(
            x=[st.session_state["gx"]],
            y=[st.session_state["gy"]],
            z=[st.session_state["gz"]],
            mode='markers+text',
            marker=dict(size=10, color='red'),
            text=['Gate'],
            textposition='top center',
            name='Gate Position',
            showlegend=True
        ))
    
    # 바운딩 박스 정보
    bb_min = mesh_obj.bounds[0]
    bb_max = mesh_obj.bounds[1]
    bb_size = bb_max - bb_min
    
    fig.update_layout(
        title="📦 Part STL Visualization",
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)",
            aspectmode="data"
        ),
        height=600,
        showlegend=True
    )
    
    st.plotly_chart(fig, use_container_width=True)
    
    # 정보 표시
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("부피 (mm³)", f"{mesh_obj.volume:.1f}")
    with col2:
        st.metric("표면적 (mm²)", f"{mesh_obj.area:.1f}")
    with col3:
        st.metric("삼각형 수", len(faces))
    
    # 바운딩 박스 정보
    st.write(f"**Bounding Box:**")
    st.write(f"- X: {bb_min[0]:.1f} ~ {bb_max[0]:.1f} mm (크기: {bb_size[0]:.1f} mm)")
    st.write(f"- Y: {bb_min[1]:.1f} ~ {bb_max[1]:.1f} mm (크기: {bb_size[1]:.1f} mm)")
    st.write(f"- Z: {bb_min[2]:.1f} ~ {bb_max[2]:.1f} mm (크기: {bb_size[2]:.1f} mm)")

def auto_suggest_gate(mesh_obj):
    """게이트 위치 자동 추천"""
    if mesh_obj is None:
        st.warning("메쉬를 먼저 로드해주세요")
        return
    
    # 바운딩 박스에서 최적 게이트 위치 계산
    bb_min = mesh_obj.bounds[0]
    bb_max = mesh_obj.bounds[1]
    center = (bb_min + bb_max) / 2
    
    # 추천 위치: 바운딩 박스 하단 중앙
    suggested_x = center[0]
    suggested_y = center[1]
    suggested_z = bb_min[2] - 2.0  # 아래쪽 약간 떨어진 곳
    
    st.session_state["gx"] = suggested_x
    st.session_state["gy"] = suggested_y
    st.session_state["gz"] = suggested_z
    st.session_state["gate_suggested"] = True
    
    st.success(f"✅ 게이트 위치 추천됨: ({suggested_x:.1f}, {suggested_y:.1f}, {suggested_z:.1f})")

# ═══════════════════════════════════════════════════════════
#  ★★★ MAIN UI ★★★
# ═══════════════════════════════════════════════════════════

# 서버 상태 확인
if not api_client.health_check():
    st.error(f"⚠️ Oracle API 연결 불가: {ORACLE_API_URL}")
    st.info("로컬 테스트: `docker-compose up -d` 실행")
    st.stop()

st.success("✅ Oracle Cloud API 연결됨")

# 탭 구성
tab1, tab2, tab3, tab4 = st.tabs([
    "🚀 Simulation",
    "📊 Results",
    "📚 Material DB",
    "⚙️ Settings"
])

# ───────────────────── TAB 1: Simulation ─────────────────────
with tab1:
    st.header("Run Simulation")
    
    # STL 파일 업로드
    st.subheader("📁 Step 1: Upload STL File")
    stl_upload = st.file_uploader("STL 파일 선택", type=["stl"])
    
    if stl_upload:
        st.info(f"✅ {stl_upload.name} ({stl_upload.size / 1e6:.1f}MB)")
        
        # 메쉬 로드
        with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp:
            tmp.write(stl_upload.getbuffer())
            tmp_path = tmp.name
        
        try:
            mesh = trimesh.load(tmp_path)
            st.session_state["mesh"] = mesh
        except Exception as e:
            st.error(f"메쉬 로드 오류: {e}")
            mesh = None
        
        # 메쉬 시각화
        st.subheader("📦 Step 2: Visualize & Set Gate Position")
        visualize_stl(st.session_state["mesh"])
        
        # 게이트 위치 설정
        col1, col2 = st.columns([3, 1])
        with col1:
            st.subheader("🎯 Gate Position")
            col_x, col_y, col_z = st.columns(3)
            with col_x:
                st.session_state["gx"] = st.number_input("Gate X (mm)", value=st.session_state["gx"], step=1.0)
            with col_y:
                st.session_state["gy"] = st.number_input("Gate Y (mm)", value=st.session_state["gy"], step=1.0)
            with col_z:
                st.session_state["gz"] = st.number_input("Gate Z (mm)", value=st.session_state["gz"], step=1.0)
            
            st.session_state["gsize"] = st.number_input("Gate Diameter (mm)", value=st.session_state["gsize"], step=0.5)
        
        with col2:
            st.write("")
            st.write("")
            if st.button("🤖 Auto Suggest", use_container_width=True):
                auto_suggest_gate(st.session_state["mesh"])
                st.rerun()
        
        st.divider()
        
        # 재료 선택
        st.subheader("⚙️ Step 3: Select Material")
        
        mat_db = load_material_db(MATERIAL_FILE)
        mat_list = sorted(mat_db.keys()) if mat_db else ["CATAMOLD-17-4PH"]
        
        # 재료 선택 시 자동값 변경
        old_mat = st.session_state["mat_name"]
        st.session_state["mat_name"] = st.selectbox("재료 선택", mat_list, index=mat_list.index(st.session_state["mat_name"]) if st.session_state["mat_name"] in mat_list else 0)
        
        # 선택된 재료의 추천값 적용
        if st.session_state["mat_name"] in mat_db:
            mat_props = mat_db[st.session_state["mat_name"]]
            
            # 재료가 변경되면 자동으로 값 업데이트
            if old_mat != st.session_state["mat_name"]:
                st.session_state["temp"] = mat_props['Tmelt']
                st.session_state["press"] = mat_props['press_mpa']
                st.session_state["vel"] = mat_props['vel_mms']
                st.success(f"✅ {st.session_state['mat_name']} 추천값으로 업데이트됨")
        
        # 시뮬레이션 파라미터
        st.subheader("📊 Step 4: Simulation Parameters")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.session_state["temp"] = st.number_input("Injection Temp (°C)", value=st.session_state["temp"], step=1.0)
            st.session_state["vel"] = st.number_input("Injection Velocity (mm/s)", value=st.session_state["vel"], step=1.0)
        
        with col2:
            st.session_state["press"] = st.number_input("Pressure (MPa)", value=st.session_state["press"], step=1.0)
            st.session_state["etime"] = st.number_input("End Time (s)", value=st.session_state["etime"], step=0.1)
        
        with col3:
            st.session_state["machine_ton"] = st.slider("Machine Tonnage", 30, 200, st.session_state["machine_ton"])
            st.session_state["num_frames"] = st.slider("Number of Frames", 5, 60, st.session_state["num_frames"])
            st.session_state["mesh_res_mm"] = st.number_input("Mesh Resolution (mm)", value=st.session_state["mesh_res_mm"], min_value=0.1, step=0.1)
        
        st.divider()
        
        # 시뮬레이션 실행
        st.subheader("🚀 Step 5: Run Simulation")
        
        col1, col2, col3 = st.columns([2, 1, 1])
        
        with col1:
            if st.button("🚀 RUN SIMULATION", type="primary", use_container_width=True):
                st.session_state["sim_running"] = True
                st.session_state["sim_logs"] = []
                
                add_log("📤 시뮬레이션을 Oracle Cloud에 제출 중...")
                
                # 시뮬레이션 매개변수
                params = {
                    'signal_id': f"SIM-{int(time.time())}",
                    'gate_x': st.session_state["gx"],
                    'gate_y': st.session_state["gy"],
                    'gate_z': st.session_state["gz"],
                    'gate_dia': st.session_state["gsize"],
                    'vel_mms': st.session_state["vel"],
                    'etime': st.session_state["etime"],
                    'num_frames': st.session_state["num_frames"],
                    'mesh_res_mm': st.session_state["mesh_res_mm"],
                    'material': st.session_state["mat_name"],
                    'screw_dia': st.session_state["screw_dia_mm"],
                }
                
                # 시뮬레이션 제출
                result = api_client.submit_simulation(tmp_path, params)
                
                if "error" in result:
                    add_log(f"❌ 오류: {result['error']}")
                    st.error(f"❌ 오류: {result['error']}")
                else:
                    job_id = result.get('job_id')
                    est_time = result.get('est_time_sec', 60)
                    st.session_state["job_id"] = job_id
                    
                    add_log(f"✅ 작업 제출 성공!")
                    add_log(f"Job ID: {job_id}")
                    add_log(f"예상 시간: {est_time}초")
                    
                    st.success(f"✅ 작업이 제출되었습니다! (ID: {job_id})")
                    st.info(f"⏳ 예상 시간: {est_time}초")
                    
                    # 모니터링
                    with st.status("🔄 작업 모니터링 중...", expanded=True) as status:
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        max_wait = 3600
                        elapsed = 0
                        
                        while elapsed < max_wait:
                            if not st.session_state["sim_running"]:
                                add_log("⏹️ 모니터링 중단됨")
                                break
                            
                            job_status = api_client.get_job_status(job_id)
                            
                            if "error" in job_status:
                                add_log(f"❌ 상태 확인 오류: {job_status['error']}")
                                time.sleep(2)
                                elapsed += 2
                                continue
                            
                            job_state = job_status.get('status', 'unknown')
                            progress = job_status.get('progress', 0)
                            elapsed_sec = job_status.get('elapsed_sec', 0)
                            
                            status_text.info(f"상태: **{job_state}** | 경과: {elapsed_sec:.0f}초 | 진행: {progress}%")
                            progress_bar.progress(min(progress / 100, 1.0))
                            
                            if job_state == 'completed':
                                add_log("✅ 작업 완료!")
                                status.update(label="✅ 완료!", state="complete")
                                st.success("✅ 시뮬레이션 완료!")
                                st.balloons()
                                break
                            elif job_state in ['failed', 'error', 'timeout']:
                                error_msg = job_status.get('error', 'Unknown error')
                                add_log(f"❌ 작업 실패: {error_msg}")
                                status.update(label=f"❌ {job_state}", state="error")
                                st.error(f"❌ 작업 실패: {error_msg}")
                                break
                            
                            time.sleep(2)
                            elapsed += 2
                        
                        if elapsed >= max_wait:
                            add_log("⏱️ 모니터링 타임아웃 (1시간)")
                            status.update(label="⏱️ 타임아웃", state="error")
                
                st.session_state["sim_running"] = False
                show_logs()
        
        with col2:
            if st.button("🔄 Clear", use_container_width=True):
                st.session_state["sim_logs"] = []
                st.session_state["job_id"] = None
        
        with col3:
            if st.button("⏹️ Stop", use_container_width=True):
                st.session_state["sim_running"] = False

# ───────────────────── TAB 2: Results ─────────────────────
with tab2:
    st.header("Simulation Results")
    
    if st.session_state["job_id"]:
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.write(f"**Job ID:** `{st.session_state['job_id']}`")
        
        with col2:
            if st.button("🔄 Fetch Results"):
                results = api_client.get_results(st.session_state["job_id"])
                if "error" not in results:
                    st.session_state["current_results"] = results
                    st.success("✅ 결과 로드됨!")
                else:
                    st.error(f"오류: {results['error']}")
        
        if st.session_state.get("current_results"):
            results = st.session_state["current_results"]
            
            if "results" in results:
                res = results["results"]
                
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Total Voxels", res.get("Total Voxels", "N/A"))
                with col2:
                    st.metric("Theo Fill Time (s)", f"{res.get('Theo Fill Time (s)', 0):.3f}")
                with col3:
                    st.metric("Solver Time (s)", f"{res.get('Solver Time (s)', 0):.2f}")
                
                st.json(res, expanded=False)
            
            if "files" in results:
                st.subheader("📥 Download Files")
                for filename in results["files"]:
                    st.write(f"- {filename}")
    else:
        st.info("💡 시뮬레이션을 실행한 후 결과를 확인하세요.")

# ───────────────────── TAB 3: Material DB ─────────────────────
with tab3:
    st.header("Material Database Management")
    
    db = load_material_db(MATERIAL_FILE)
    
    if db:
        df = pd.DataFrame([
            {
                "Material": k,
                "ν (m²/s)": f"{v['nu']:.2e}",
                "ρ (kg/m³)": f"{v['rho']:.0f}",
                "Tmelt (°C)": f"{v['Tmelt']:.1f}",
                "Tmold (°C)": f"{v['Tmold']:.1f}",
                "P (MPa)": f"{v['press_mpa']:.1f}",
                "Vel (mm/s)": f"{v['vel_mms']:.1f}"
            }
            for k, v in sorted(db.items())
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("데이터베이스가 비어있습니다.")
    
    st.divider()
    st.subheader("Add / Update Material")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        new_mat = st.text_input("Material Name")
        new_nu = st.number_input("Viscosity (m²/s)", value=4e-3, format="%.2e")
        new_rho = st.number_input("Density (kg/m³)", value=7800.0)
    with col2:
        new_tmelt = st.number_input("Melt Temp (°C)", value=185.0)
        new_tmold = st.number_input("Mold Temp (°C)", value=40.0)
    with col3:
        new_press = st.number_input("Press (MPa)", value=110.0)
        new_vel = st.number_input("Vel (mm/s)", value=25.0)
    
    if st.button("💾 Save to DB", type="primary", use_container_width=True):
        if new_mat.strip():
            save_material_to_txt(new_mat.strip(), {
                'nu': new_nu,
                'rho': new_rho,
                'Tmelt': new_tmelt,
                'Tmold': new_tmold,
                'press_mpa': new_press,
                'vel_mms': new_vel
            })
            st.success(f"✅ {new_mat} 저장됨!")
            st.rerun()
        else:
            st.warning("재료명을 입력하세요")

# ───────────────────── TAB 4: Settings ─────────────────────
with tab4:
    st.header("Settings")
    
    st.subheader("🔗 API Configuration")
    st.write(f"**API URL:** `{ORACLE_API_URL}`")
    st.write(f"**API Key:** {'설정됨' if ORACLE_API_KEY != 'default-key-change-in-production' else '⚠️ 기본값 (변경 필요)'}")
    
    st.info("API URL과 Key는 `.streamlit/secrets.toml`에서 설정합니다")
    
    st.subheader("ℹ️ About")
    st.markdown("""
    **MIM-Ops Pro v3.2 - Oracle Cloud Edition**
    
    - **UI:** Streamlit
    - **Backend:** Flask REST API
    - **Compute:** Oracle Cloud
    - **Storage:** Oracle Object Storage
    - **Solver:** Python-based (trimesh, scipy)
    
    [GitHub](https://github.com/workshopcompany/MIM-Ops-Oracle)
    """)
