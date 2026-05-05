"""
MIM-Ops Pro v3.2 - Oracle Cloud Edition
========================================
GitHub Actions 대신 Oracle Cloud API를 사용하는 Streamlit 앱
"""

import streamlit as st
import os
import time
import requests
import json
from datetime import datetime
import numpy as np
import tempfile

st.set_page_config(page_title="MIM-Ops Pro", page_icon="🔬", layout="wide")
st.title("🔬 MIM-Ops Pro v3.2: Oracle Cloud Edition")

# ── Configuration ──
ORACLE_API_URL = st.secrets.get("ORACLE_API_URL", "http://localhost:5000")
ORACLE_API_KEY = st.secrets.get("ORACLE_API_KEY", "default-key")

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
_init("mat_name", "17-4PH")
_init("machine_ton", 50)
_init("screw_dia_mm", 28.0)
_init("current_results", None)
_init("polling_interval", 2)  # 상태 조회 간격 (초)

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
                    'material': params.get('material', '17-4PH'),
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
                    return {"error": f"API Error: {response.status_code}", "detail": response.text}
        except Exception as e:
            return {"error": f"Request failed: {str(e)}"}
    
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
                return {"error": f"Status code: {response.status_code}"}
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
                return {"error": f"Status code: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
    
    def cancel_job(self, job_id):
        """작업 취소"""
        try:
            response = requests.delete(
                f"{self.api_url}/api/jobs/{job_id}",
                headers=self.headers,
                timeout=10
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Cancel error: {e}")
            return False

api_client = OracleAPIClient(ORACLE_API_URL, ORACLE_API_KEY)

# ───────────────────── 시뮬레이션 실행 ─────────────────────
def start_simulation(stl_path, params):
    """시뮬레이션 시작"""
    add_log("📤 Submitting simulation to Oracle Cloud...")
    
    result = api_client.submit_simulation(stl_path, params)
    
    if "error" in result:
        add_log(f"❌ Error: {result['error']}")
        if "detail" in result:
            add_log(f"Details: {result['detail']}")
        return None
    
    job_id = result.get('job_id')
    est_time = result.get('est_time_sec', 60)
    
    add_log(f"✅ Job submitted successfully!")
    add_log(f"Job ID: {job_id}")
    add_log(f"Estimated time: {est_time}s")
    
    return job_id

def monitor_job(job_id):
    """작업 모니터링"""
    add_log(f"⏳ Monitoring job {job_id}...")
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    max_wait = 3600  # 1시간
    elapsed = 0
    
    while elapsed < max_wait:
        if not st.session_state["sim_running"]:
            add_log("⏹️  Monitoring cancelled by user")
            break
        
        status = api_client.get_job_status(job_id)
        
        if "error" in status:
            add_log(f"❌ Error checking status: {status['error']}")
            time.sleep(st.session_state["polling_interval"])
            elapsed += st.session_state["polling_interval"]
            continue
        
        job_status = status.get('status', 'unknown')
        progress = status.get('progress', 0)
        elapsed_sec = status.get('elapsed_sec', 0)
        
        status_text.info(f"Status: **{job_status}** | Elapsed: {elapsed_sec:.0f}s | Progress: {progress}%")
        progress_bar.progress(min(progress / 100, 1.0))
        
        if job_status == 'completed':
            add_log("✅ Job completed!")
            return True
        elif job_status in ['failed', 'error', 'timeout']:
            error_msg = status.get('error', 'Unknown error')
            add_log(f"❌ Job {job_status}: {error_msg}")
            return False
        elif job_status == 'cancelled':
            add_log("⏹️  Job cancelled")
            return False
        
        time.sleep(st.session_state["polling_interval"])
        elapsed += st.session_state["polling_interval"]
    
    add_log("⏱️  Monitoring timeout (1 hour)")
    return False

# ───────────────────── Material DB ─────────────────────
@st.cache_data(ttl=10)
def load_material_db(filepath: str) -> dict:
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
                if len(parts) >= 6:
                    mat_name = parts[0]
                    db[mat_name] = {
                        'nu': float(parts[1]),
                        'rho': float(parts[2]),
                        'Tmelt': float(parts[3]),
                        'Tmold': float(parts[4]),
                        'press_mpa': float(parts[5]),
                    }
    except Exception as e:
        st.warning(f"Material DB load error: {e}")
    
    return db

def save_material_to_txt(name: str, props: dict) -> bool:
    """재료 저장"""
    try:
        db = load_material_db(MATERIAL_FILE)
        db[name] = props
        
        os.makedirs(os.path.dirname(MATERIAL_FILE) or '.', exist_ok=True)
        
        with open(MATERIAL_FILE, 'w') as f:
            for mat, p in sorted(db.items()):
                line = f"{mat}|{p['nu']:.2e}|{p['rho']:.0f}|{p['Tmelt']:.1f}|{p['Tmold']:.1f}|{p['press_mpa']:.1f}\n"
                f.write(line)
        
        st.cache_data.clear()
        return True
    except Exception as e:
        st.error(f"Save error: {e}")
        return False

# ═══════════════════════════════════════════════════════════
#  UI Layout
# ═══════════════════════════════════════════════════════════

# 서버 상태 확인
if not api_client.health_check():
    st.error(f"⚠️ Cannot connect to Oracle API: {ORACLE_API_URL}")
    st.stop()

st.success("✅ Connected to Oracle Cloud API")

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
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📁 Input File")
        stl_upload = st.file_uploader("Upload STL file", type=["stl"])
        
        if stl_upload:
            st.info(f"File: {stl_upload.name} ({stl_upload.size / 1e6:.1f}MB)")
    
    with col2:
        st.subheader("🎯 Gate Position")
        st.session_state["gx"] = st.number_input("Gate X (mm)", value=st.session_state["gx"])
        st.session_state["gy"] = st.number_input("Gate Y (mm)", value=st.session_state["gy"])
        st.session_state["gz"] = st.number_input("Gate Z (mm)", value=st.session_state["gz"])
        st.session_state["gsize"] = st.number_input("Gate Diameter (mm)", value=st.session_state["gsize"])
    
    st.divider()
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.subheader("🌡️ Process Parameters")
        st.session_state["temp"] = st.number_input("Injection Temp (°C)", value=st.session_state["temp"])
        st.session_state["press"] = st.number_input("Pressure (MPa)", value=st.session_state["press"])
    
    with col2:
        st.subheader("⚙️ Screw & Material")
        mat_db = load_material_db(MATERIAL_FILE)
        mat_list = list(mat_db.keys()) if mat_db else ["17-4PH"]
        st.session_state["mat_name"] = st.selectbox("Material", mat_list)
        st.session_state["screw_dia_mm"] = st.number_input("Screw Diameter (mm)", value=st.session_state["screw_dia_mm"])
    
    with col3:
        st.subheader("⏱️ Simulation Time")
        st.session_state["vel"] = st.number_input("Injection Velocity (mm/s)", value=st.session_state["vel"])
        st.session_state["etime"] = st.number_input("End Time (s)", value=st.session_state["etime"])
    
    st.divider()
    
    # 시뮬레이션 실행 버튼
    col1, col2, col3 = st.columns([2, 1, 1])
    
    with col1:
        if st.button("🚀 Run Simulation", type="primary", use_container_width=True):
            if not stl_upload:
                st.error("Please upload an STL file")
            else:
                st.session_state["sim_running"] = True
                st.session_state["sim_logs"] = []
                
                # 임시 파일 저장
                with tempfile.NamedTemporaryFile(delete=False, suffix=".stl") as tmp:
                    tmp.write(stl_upload.getbuffer())
                    tmp_path = tmp.name
                
                try:
                    # 시뮬레이션 매개변수
                    params = {
                        'signal_id': f"SIM-{int(time.time())}",
                        'gate_x': st.session_state["gx"],
                        'gate_y': st.session_state["gy"],
                        'gate_z': st.session_state["gz"],
                        'gate_dia': st.session_state["gsize"],
                        'vel_mms': st.session_state["vel"],
                        'etime': st.session_state["etime"],
                        'num_frames': 15,
                        'mesh_res_mm': 0.5,
                        'material': st.session_state["mat_name"],
                        'screw_dia': st.session_state["screw_dia_mm"],
                    }
                    
                    # 시뮬레이션 시작
                    job_id = start_simulation(tmp_path, params)
                    
                    if job_id:
                        st.session_state["job_id"] = job_id
                        
                        # 로그 표시
                        show_logs()
                        
                        # 모니터링
                        if monitor_job(job_id):
                            st.session_state["sim_status"] = "completed"
                            st.success("✅ Simulation completed!")
                            st.rerun()
                        else:
                            st.session_state["sim_status"] = "failed"
                            st.error("❌ Simulation failed")
                    else:
                        st.session_state["sim_status"] = "error"
                
                finally:
                    st.session_state["sim_running"] = False
                    os.unlink(tmp_path)
    
    with col2:
        if st.button("🔄 Clear", use_container_width=True):
            st.session_state["sim_logs"] = []
            st.session_state["job_id"] = None
    
    with col3:
        if st.button("⏹️ Stop", use_container_width=True):
            if st.session_state["job_id"]:
                api_client.cancel_job(st.session_state["job_id"])
                add_log("Job cancellation requested")
            st.session_state["sim_running"] = False
    
    st.divider()
    show_logs()

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
                    st.success("Results loaded!")
                else:
                    st.error(f"Error: {results['error']}")
        
        if st.session_state.get("current_results"):
            results = st.session_state["current_results"]
            
            # 결과 표시
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
            
            # 파일 다운로드
            if "files" in results:
                st.subheader("📥 Download Files")
                for filename in results["files"]:
                    st.write(f"- {filename}")
    else:
        st.info("No simulation results. Run a simulation first.")

# ───────────────────── TAB 3: Material DB ─────────────────────
with tab3:
    st.header("Material Database Management")
    
    db = load_material_db(MATERIAL_FILE)
    
    if db:
        import pandas as pd
        df = pd.DataFrame([
            {
                "Material": k,
                "ν (m²/s)": f"{v['nu']:.2e}",
                "ρ (kg/m³)": f"{v['rho']:.0f}",
                "Tmelt (°C)": f"{v['Tmelt']:.1f}",
                "Tmold (°C)": f"{v['Tmold']:.1f}",
                "P (MPa)": f"{v['press_mpa']:.1f}",
            }
            for k, v in sorted(db.items())
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("Database is empty")
    
    st.divider()
    st.subheader("Add / Update Material")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        new_mat = st.text_input("Material Name")
        new_nu = st.number_input("Viscosity (m²/s)", value=4e-3, format="%.2e")
    with col2:
        new_rho = st.number_input("Density (kg/m³)", value=7800.0)
        new_tmelt = st.number_input("Melt Temp (°C)", value=185.0)
    with col3:
        new_tmold = st.number_input("Mold Temp (°C)", value=40.0)
        new_press = st.number_input("Press (MPa)", value=110.0)
    
    if st.button("💾 Save to DB", type="primary", use_container_width=True):
        if new_mat.strip():
            save_material_to_txt(new_mat.strip(), {
                'nu': new_nu,
                'rho': new_rho,
                'Tmelt': new_tmelt,
                'Tmold': new_tmold,
                'press_mpa': new_press,
            })
            st.success(f"✅ {new_mat} saved!")
            st.rerun()
        else:
            st.warning("Please enter a material name")

# ───────────────────── TAB 4: Settings ─────────────────────
with tab4:
    st.header("Settings")
    
    st.subheader("🔗 API Configuration")
    st.write(f"**API URL:** `{ORACLE_API_URL}`")
    st.write(f"**API Key:** {'Set' if ORACLE_API_KEY != 'default-key' else '⚠️ Default (change in settings)'}")
    
    st.info("API URL and Key should be set in `.streamlit/secrets.toml`")
    
    st.subheader("⏱️ Monitoring")
    st.session_state["polling_interval"] = st.slider(
        "Status Check Interval (seconds)",
        min_value=1,
        max_value=10,
        value=st.session_state["polling_interval"]
    )
    
    st.subheader("ℹ️ About")
    st.markdown("""
    **MIM-Ops Pro v3.2 - Oracle Cloud Edition**
    
    - **UI:** Streamlit
    - **Backend:** Flask REST API
    - **Compute:** Oracle Cloud (Compute Instances)
    - **Storage:** Oracle Object Storage
    - **Solver:** Python-based (trimesh, scipy, matplotlib)
    
    [GitHub](https://github.com/workshopcompany/MIM-Ops-Oracle)
    """)
