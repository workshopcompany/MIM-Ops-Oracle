"""
MIM-Ops Pro API Server
========================
Oracle Cloud 배포용 REST API 서버
Flask + Oracle Object Storage + Solver 연동

엔드포인트:
  POST   /api/simulate       - 시뮬레이션 요청
  GET    /api/jobs/{job_id}  - 작업 상태 조회
  GET    /api/results/{job_id} - 결과 다운로드
  DELETE /api/jobs/{job_id}  - 작업 취소/정리
  GET    /health            - 헬스 체크
"""

import os
import json
import uuid
import time
import tempfile
import threading
import traceback
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import dotenv

# Oracle SDK
try:
    import oci
    HAS_ORACLE_SDK = True
except ImportError:
    HAS_ORACLE_SDK = False
    print("[API] Warning: oci 패키지 미설치 — Object Storage 기능 비활성화")

# Solver
import subprocess
from subprocess import run as subprocess_run
import numpy as np

# ═══════════════════════════════════════════════════════════
# ★ Configuration
# ═══════════════════════════════════════════════════════════

dotenv.load_dotenv()

app = Flask(__name__)
CORS(app)

# 설정
CONFIG = {
    "API_KEY": os.getenv("API_KEY", "default-key-change-in-production"),
    "MAX_FILE_SIZE": int(os.getenv("MAX_FILE_SIZE", 100 * 1024 * 1024)),  # 100MB
    "SOLVER_TIMEOUT": int(os.getenv("SOLVER_TIMEOUT", 3600)),  # 1시간
    "ORACLE": {
        "use_oracle": HAS_ORACLE_SDK and os.getenv("USE_ORACLE", "false").lower() == "true",
        "compartment_id": os.getenv("ORACLE_COMPARTMENT_ID", ""),
        "bucket_name": os.getenv("ORACLE_BUCKET_NAME", "mim-ops-results"),
        "region": os.getenv("ORACLE_REGION", "ap-seoul-1"),
    },
    "TEMP_DIR": os.getenv("TEMP_DIR", "/tmp/mim-ops"),
    "RESULTS_DIR": os.getenv("RESULTS_DIR", "./results"),
}

# 디렉토리 생성
os.makedirs(CONFIG["TEMP_DIR"], exist_ok=True)
os.makedirs(CONFIG["RESULTS_DIR"], exist_ok=True)

# 작업 상태 저장소 (프로덕션에서는 Redis/DB 사용)
JOBS = {}

# ═══════════════════════════════════════════════════════════
# ★ Oracle Storage Client
# ═══════════════════════════════════════════════════════════

class OracleStorageClient:
    """Oracle Object Storage 클라이언트"""
    
    def __init__(self):
        self.enabled = CONFIG["ORACLE"]["use_oracle"]
        if self.enabled:
            try:
                # OCI SDK 초기화 (기본값: ~/.oci/config 파일 사용)
                self.client = oci.object_storage.ObjectStorageClient(
                    oci.config.from_file()
                )
                self.namespace = self.client.get_namespace().data
                print(f"[Oracle] Connected to namespace: {self.namespace}")
            except Exception as e:
                print(f"[Oracle] ⚠️ Connection failed: {e}")
                self.enabled = False
    
    def upload_file(self, file_path, object_name, job_id):
        """파일을 Object Storage에 업로드"""
        if not self.enabled:
            return None
        
        try:
            with open(file_path, 'rb') as f:
                self.client.put_object(
                    namespace_name=self.namespace,
                    bucket_name=CONFIG["ORACLE"]["bucket_name"],
                    object_name=f"{job_id}/{object_name}",
                    put_object_body=f
                )
            print(f"[Oracle] ✅ Uploaded: {job_id}/{object_name}")
            return f"oci://{CONFIG['ORACLE']['bucket_name']}/{job_id}/{object_name}"
        except Exception as e:
            print(f"[Oracle] ❌ Upload error: {e}")
            return None
    
    def download_file(self, object_name, job_id, local_path):
        """Object Storage에서 파일 다운로드"""
        if not self.enabled:
            return False
        
        try:
            response = self.client.get_object(
                namespace_name=self.namespace,
                bucket_name=CONFIG["ORACLE"]["bucket_name"],
                object_name=f"{job_id}/{object_name}"
            )
            with open(local_path, 'wb') as f:
                f.write(response.data.content)
            print(f"[Oracle] ✅ Downloaded: {job_id}/{object_name}")
            return True
        except Exception as e:
            print(f"[Oracle] ❌ Download error: {e}")
            return False
    
    def list_objects(self, job_id):
        """작업의 모든 객체 나열"""
        if not self.enabled:
            return []
        
        try:
            response = self.client.list_objects(
                namespace_name=self.namespace,
                bucket_name=CONFIG["ORACLE"]["bucket_name"],
                prefix=f"{job_id}/"
            )
            return [obj.name for obj in response.data.objects]
        except Exception as e:
            print(f"[Oracle] ❌ List error: {e}")
            return []
    
    def cleanup(self, job_id):
        """작업 완료 후 정리"""
        if not self.enabled:
            return True
        
        try:
            objects = self.list_objects(job_id)
            for obj in objects:
                self.client.delete_object(
                    namespace_name=self.namespace,
                    bucket_name=CONFIG["ORACLE"]["bucket_name"],
                    object_name=obj
                )
            print(f"[Oracle] ✅ Cleaned up: {job_id}")
            return True
        except Exception as e:
            print(f"[Oracle] ❌ Cleanup error: {e}")
            return False

oracle_client = OracleStorageClient()

# ═══════════════════════════════════════════════════════════
# ★ 인증
# ═══════════════════════════════════════════════════════════

def require_api_key(f):
    """API Key 검증 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not api_key or api_key != CONFIG["API_KEY"]:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ═══════════════════════════════════════════════════════════
# ★ Solver 실행
# ═══════════════════════════════════════════════════════════

def run_solver(job_id, stl_path, params):
    """solver.py 실행 (별도 스레드)"""
    job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
    os.makedirs(job_dir, exist_ok=True)

    log_lines = []

    try:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["start_time"] = datetime.now()
        JOBS[job_id]["log"] = []

        print(f"[Solver] Starting job {job_id}...")

        # ── solver.py 위치를 절대경로로 확정 ──────────────────────────
        # 후보 경로를 순서대로 탐색:
        #   1) 이 server.py 와 같은 디렉토리
        #   2) /app/solver/solver.py  (Docker 표준 경로)
        #   3) /app/solver.py
        server_dir  = os.path.dirname(os.path.abspath(__file__))
        solver_candidates = [
            os.path.join(server_dir, "solver", "solver.py"),
            os.path.join(server_dir, "solver.py"),
            "/app/solver/solver.py",
            "/app/solver.py",
        ]
        solver_py = None
        for c in solver_candidates:
            if os.path.isfile(c):
                solver_py = c
                break

        if solver_py is None:
            err = (
                f"solver.py를 찾을 수 없습니다. 탐색한 경로: {solver_candidates}"
            )
            print(f"[Solver] ❌ {err}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"]  = err
            JOBS[job_id]["log"]    = [err]
            return

        print(f"[Solver] Using solver: {solver_py}")

        # ── stl_path 절대경로 보장 ────────────────────────────────────
        stl_abs = os.path.abspath(stl_path) if not os.path.isabs(stl_path) \
                  else stl_path
        if not os.path.isfile(stl_abs):
            err = f"STL 파일을 찾을 수 없습니다: {stl_abs}"
            print(f"[Solver] ❌ {err}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"]  = err
            JOBS[job_id]["log"]    = [err]
            return

        # Solver 명령 구성 (절대경로 사용, cwd 불필요)
        cmd = [
            "python", solver_py,
            "--signal_id", job_id,
            "--stl_path",  stl_abs,          # ★ 절대경로
            "--gate_x",    str(params.get("gate_x", 0.0)),
            "--gate_y",    str(params.get("gate_y", 0.0)),
            "--gate_z",    str(params.get("gate_z", 0.0)),
            "--gate_dia",  str(params.get("gate_dia", 2.0)),
            "--vel_mms",   str(params.get("vel_mms", 25.0)),
            "--etime",     str(params.get("etime", 1.0)),
            "--num_frames",str(params.get("num_frames", 15)),
            "--mesh_res_mm",str(params.get("mesh_res_mm", 0.5)),
            "--material",  str(params.get("material", "17-4PH")),
            "--screw_dia", str(params.get("screw_dia", 28.0)),
        ]

        import re

        process = subprocess.Popen(
            cmd,
            cwd=job_dir,                     # 작업 디렉토리는 job_dir 유지
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        deadline = time.time() + CONFIG["SOLVER_TIMEOUT"]

        for line in process.stdout:
            line = line.rstrip()
            if line:
                print(f"[Solver][{job_id}] {line}")
                log_lines.append(line)

                # [Issue #3] 진행률 파싱 우선순위:
                # 1순위: "PROGRESS:50" 형식 (solver.py 에서 명시적 출력)
                # 2순위: "50%" 형식 (레거시 호환)
                m = re.search(r"PROGRESS[:\s]+(\d+)", line, re.IGNORECASE)
                if m:
                    pct = min(int(m.group(1)), 99)
                    JOBS[job_id]["progress"] = pct
                else:
                    # 소수점 포함 % 패턴도 처리: "Fill: 6.7%" → 6 캡처
                    m2 = re.search(r"\b(\d{1,3})(?:\.\d+)?\s*%", line)
                    if m2:
                        pct2 = min(int(m2.group(1)), 99)
                        # 현재 progress 보다 높을 때만 업데이트 (역행 방지)
                        if pct2 > JOBS[job_id].get("progress", 0):
                            JOBS[job_id]["progress"] = pct2

                # [Issue #3] 오류 키워드 감지 시 즉시 error 필드 업데이트
                if any(kw in line for kw in ["MemoryError", "OOM", "Killed", "killed",
                                              "Error", "Exception", "Traceback"]):
                    JOBS[job_id]["last_error_line"] = line

            if time.time() > deadline:
                process.kill()
                JOBS[job_id]["status"] = "timeout"
                JOBS[job_id]["error"] = f"Timeout after {CONFIG['SOLVER_TIMEOUT']}s"
                JOBS[job_id]["log"] = log_lines[-100:]  # 마지막 100줄 보존
                print(f"[Solver] ⏱️ Timeout: {job_id}")
                return

        process.wait()

        if process.returncode != 0:
            # [Issue #3] 실패 시 로그 전체를 error 필드에 저장
            error_summary = JOBS[job_id].get("last_error_line", f"Solver exited with code {process.returncode}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = error_summary
            JOBS[job_id]["return_code"] = process.returncode
            JOBS[job_id]["log"] = log_lines[-100:]  # 마지막 100줄 보존
            print(f"[Solver] ❌ Job failed with return code {process.returncode}")
            print(f"[Solver] ❌ Last error: {error_summary}")
            return
        
        # 결과 처리
        results_file = os.path.join(job_dir, "results.json")
        if os.path.exists(results_file):
            with open(results_file) as f:
                results = json.load(f)
            JOBS[job_id]["results"] = results

            if oracle_client.enabled:
                oracle_client.upload_file(results_file, "results.json", job_id)

        # ── ★ 수정: 실제 저장된 파일 목록 확인 후 completed 판정 ──
        frames_dir_check = os.path.join(job_dir, "frames")
        frames_exist = (
            os.path.isdir(frames_dir_check) and
            any(f.endswith(".png") for f in os.listdir(frames_dir_check))
        )
        npz_exists     = os.path.isfile(os.path.join(job_dir, "voxel_data.npz"))
        results_exists = os.path.isfile(os.path.join(job_dir, "results.json"))

        print(f"[Solver] Output check — results.json:{results_exists} "
              f"voxel_data.npz:{npz_exists} frames:{frames_exist}", flush=True)

        if not results_exists:
            # 파일이 없으면 solver가 실제로 완료되지 않은 것
            err = (
                "solver가 종료됐지만 results.json이 없습니다. "
                "solver 로그를 확인하세요."
            )
            JOBS[job_id]["status"]      = "failed"
            JOBS[job_id]["error"]       = err
            JOBS[job_id]["log"]         = log_lines[-100:]
            JOBS[job_id]["return_code"] = 0   # 종료코드는 0이었으나 파일 없음
            print(f"[Solver] ❌ {err}")
            return
        
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["end_time"] = datetime.now()
        JOBS[job_id]["log"] = log_lines[-50:]  # 완료 시에도 마지막 50줄 보존
        print(f"[Solver] ✅ Job completed: {job_id}")
        
    except subprocess.TimeoutExpired:
        JOBS[job_id]["status"] = "timeout"
        JOBS[job_id]["error"] = f"Timeout after {CONFIG['SOLVER_TIMEOUT']}s"
        JOBS[job_id]["log"] = log_lines[-100:]
        print(f"[Solver] ⏱️ Timeout: {job_id}")
    except Exception as e:
        JOBS[job_id]["status"] = "error"
        JOBS[job_id]["error"] = str(e)
        JOBS[job_id]["log"] = log_lines[-100:]
        print(f"[Solver] 💥 Error: {e}")
        traceback.print_exc()

# ═══════════════════════════════════════════════════════════
# ★ REST API Endpoints
# ═══════════════════════════════════════════════════════════

@app.route("/health", methods=["GET"])
def health_check():
    """헬스 체크"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "oracle_enabled": oracle_client.enabled,
    }), 200

@app.route("/api/simulate", methods=["POST"])
@require_api_key
def submit_simulation():
    """
    시뮬레이션 요청
    
    Request Body:
    {
        "signal_id": "SIM-001",
        "gate_x": 0.0, "gate_y": 0.0, "gate_z": 0.0,
        "gate_dia": 2.0,
        "vel_mms": 25.0,
        "etime": 1.0,
        "num_frames": 15,
        "mesh_res_mm": 0.5,
        "material": "17-4PH",
        "screw_dia": 28.0
    }
    
    STL 파일은 multipart/form-data로 전송 (key: "stl_file")
    """
    try:
        # STL 파일 확인
        if "stl_file" not in request.files:
            return jsonify({"error": "Missing stl_file"}), 400
        
        stl_file = request.files["stl_file"]
        if not stl_file.filename.endswith(".stl"):
            return jsonify({"error": "File must be .stl"}), 400
        
        # 파일 크기 확인
        stl_file.seek(0, 2)  # EOF로 이동
        file_size = stl_file.tell()
        stl_file.seek(0)  # 처음으로 복귀
        
        if file_size > CONFIG["MAX_FILE_SIZE"]:
            return jsonify({"error": f"File too large (max {CONFIG['MAX_FILE_SIZE']/1e6}MB)"}), 413
        
        # 파라미터 파싱
        try:
            data = request.form.to_dict()
            params = {
                "signal_id": data.get("signal_id", "auto"),
                "gate_x": float(data.get("gate_x", 0.0)),
                "gate_y": float(data.get("gate_y", 0.0)),
                "gate_z": float(data.get("gate_z", 0.0)),
                "gate_dia": float(data.get("gate_dia", 2.0)),
                "vel_mms": float(data.get("vel_mms", 25.0)),
                "etime": float(data.get("etime", 1.0)),
                "num_frames": int(data.get("num_frames", 15)),
                "mesh_res_mm": float(data.get("mesh_res_mm", 0.5)),
                "material": data.get("material", "17-4PH"),
                "screw_dia": float(data.get("screw_dia", 28.0)),
            }
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid parameters: {e}"}), 400
        
        # Job ID 생성
        job_id = str(uuid.uuid4())[:12]
        if params["signal_id"] != "auto":
            job_id = params["signal_id"]
        
        # Job 디렉토리
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        # STL 파일 저장
        stl_path = os.path.join(job_dir, "input.stl")
        stl_file.save(stl_path)
        
        # Job 상태 초기화
        JOBS[job_id] = {
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "params": params,
            "file_size_mb": file_size / 1e6,
            "progress": 0,
            "error": None,
            "log": [],
        }
        
        # Solver 실행 (백그라운드 스레드)
        thread = threading.Thread(
            target=run_solver,
            args=(job_id, stl_path, params),
            daemon=True
        )
        thread.start()
        
        return jsonify({
            "job_id": job_id,
            "status": "queued",
            "message": "Simulation queued successfully",
            "est_time_sec": 60,  # 예상 시간 (실제로는 메쉬 크기에 따라 다름)
        }), 202
    
    except Exception as e:
        print(f"[API] Error in /simulate: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs/<job_id>", methods=["GET"])
@require_api_key
def get_job_status(job_id):
    """작업 상태 조회"""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    job = JOBS[job_id]
    
    # 경과 시간 계산
    if "start_time" in job:
        elapsed = (datetime.now() - job["start_time"]).total_seconds()
    else:
        elapsed = 0
    
    response = {
        "job_id": job_id,
        "status": job["status"],
        "created_at": job["created_at"],
        "elapsed_sec": elapsed,
        "progress": job.get("progress", 0),
    }
    
    # [Issue #3] failed / error / timeout 상태에서 error 메시지와 로그 포함
    if job["status"] in ("failed", "error", "timeout"):
        response["error"] = job.get("error") or "알 수 없는 오류"
        response["log"] = job.get("log", [])
        response["return_code"] = job.get("return_code")
    
    if job["status"] == "completed":
        response["results_url"] = f"/api/results/{job_id}"
    
    return jsonify(response), 200

@app.route("/api/results/<job_id>", methods=["GET"])
@require_api_key
def get_results(job_id):
    """결과 다운로드"""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    job = JOBS[job_id]
    if job["status"] != "completed":
        return jsonify({"error": f"Job status is {job['status']}",
                        "detail": job.get("error")}), 400
    
    try:
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)

        # 결과 파일들 수집
        result_files = []
        for filename in ["results.json", "results.txt", "voxel_data.npz"]:
            if os.path.exists(os.path.join(job_dir, filename)):
                result_files.append(filename)

        # frames 디렉토리 PNG 수 확인
        frames_dir = os.path.join(job_dir, "frames")
        num_frames = 0
        if os.path.isdir(frames_dir):
            pngs = [f for f in os.listdir(frames_dir) if f.endswith(".png")]
            num_frames = len(pngs)
            if num_frames > 0:
                result_files.append(f"frames/ ({num_frames} PNGs)")
        
        # 결과 구성
        response_data = {
            "job_id": job_id,
            "status": "completed",
            "completed_at": job.get("end_time", datetime.now()).isoformat(),
            "files": result_files,
        }
        
        # results.json 포함
        results_path = os.path.join(job_dir, "results.json")
        if os.path.exists(results_path):
            with open(results_path) as f:
                response_data["results"] = json.load(f)
        
        return jsonify(response_data), 200
    
    except Exception as e:
        print(f"[API] Error in /results: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/voxels/<job_id>", methods=["GET"])
@require_api_key
def get_voxel_file(job_id):
    """voxel_data.npz 바이너리 반환"""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
    npz_path = os.path.join(job_dir, "voxel_data.npz")
    if not os.path.exists(npz_path):
        return jsonify({"error": "voxel_data.npz not found — solver may still be running"}), 404
    return send_file(npz_path, mimetype="application/octet-stream",
                     as_attachment=True, download_name="voxel_data.npz")


@app.route("/api/frames/<job_id>", methods=["GET"])
@require_api_key
def get_frames(job_id):
    """
    frames/ 디렉토리의 PNG 파일을 base64로 인코딩해 JSON으로 반환.
    Streamlit 에서 st.image() 로 바로 표시 가능.

    Response:
    {
      "job_id": "...",
      "num_frames": 15,
      "frames": ["data:image/png;base64,...", ...]   // 순서대로
    }
    """
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404

    job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
    frames_dir = os.path.join(job_dir, "frames")

    if not os.path.exists(frames_dir):
        return jsonify({"error": "frames directory not found"}), 404

    png_files = sorted([f for f in os.listdir(frames_dir) if f.endswith(".png")])
    if not png_files:
        return jsonify({"error": "No PNG frames found"}), 404

    import base64 as _b64
    frame_data = []
    for fname in png_files:
        fpath = os.path.join(frames_dir, fname)
        with open(fpath, "rb") as fh:
            b64 = _b64.b64encode(fh.read()).decode("utf-8")
        frame_data.append(f"data:image/png;base64,{b64}")

    return jsonify({
        "job_id": job_id,
        "num_frames": len(frame_data),
        "frames": frame_data,
    }), 200


@app.route("/api/jobs/<job_id>", methods=["DELETE"])
@require_api_key
def cancel_job(job_id):
    """작업 취소 및 정리"""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    try:
        job = JOBS[job_id]
        
        # 실행 중이면 중단 (프로세스 레벨)
        if job["status"] == "running":
            job["status"] = "cancelled"
        
        # 로컬 파일 삭제
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
        if os.path.exists(job_dir):
            import shutil
            shutil.rmtree(job_dir)
        
        # Oracle Storage 정리
        if oracle_client.enabled:
            oracle_client.cleanup(job_id)
        
        del JOBS[job_id]
        
        return jsonify({"status": "deleted"}), 200
    
    except Exception as e:
        print(f"[API] Error in DELETE: {e}")
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════
# ★ 에러 핸들러
# ═══════════════════════════════════════════════════════════

@app.errorhandler(404)
def not_found(error):
    return jsonify({"error": "Not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    return jsonify({"error": "Internal server error"}), 500

# ═══════════════════════════════════════════════════════════
# ★ Main
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════════════╗
    ║   MIM-Ops Pro API Server                       ║
    ║   Oracle Cloud Edition                         ║
    ╚════════════════════════════════════════════════╝
    """)
    print(f"📌 Configuration:")
    print(f"   - API Key: {'set' if CONFIG['API_KEY'] != 'default-key-change-in-production' else '⚠️ DEFAULT (change in production)'}")
    print(f"   - Oracle Storage: {'✅ Enabled' if oracle_client.enabled else '❌ Disabled'}")
    print(f"   - Results Dir: {CONFIG['RESULTS_DIR']}")
    print(f"   - Max File Size: {CONFIG['MAX_FILE_SIZE']/1e6:.0f}MB")
    print()
    
    # Flask 서버 시작
    app.run(
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 5000)),
        debug=os.getenv("DEBUG", "false").lower() == "true"
    )
