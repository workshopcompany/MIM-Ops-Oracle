"""
MIM-Ops Pro API Server
========================
REST API server for Oracle Cloud deployment
Flask + Oracle Object Storage + Solver integration

Endpoints:
  POST   /api/simulate         - Submit simulation
  GET    /api/jobs/{job_id}    - Query job status
  GET    /api/results/{job_id} - Download results
  DELETE /api/jobs/{job_id}    - Cancel / clean up job
  GET    /health               - Health check
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
    print("[API] Warning: oci package not installed — Object Storage disabled")

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

# Settings
CONFIG = {
    "API_KEY": os.getenv("API_KEY", "default-key-change-in-production"),
    "MAX_FILE_SIZE": int(os.getenv("MAX_FILE_SIZE", 100 * 1024 * 1024)),  # 100MB
    "SOLVER_TIMEOUT": int(os.getenv("SOLVER_TIMEOUT", 3600)),  # 1 hour
    "ORACLE": {
        "use_oracle": HAS_ORACLE_SDK and os.getenv("USE_ORACLE", "false").lower() == "true",
        "compartment_id": os.getenv("ORACLE_COMPARTMENT_ID", ""),
        "bucket_name": os.getenv("ORACLE_BUCKET_NAME", "mim-ops-results"),
        "region": os.getenv("ORACLE_REGION", "ap-seoul-1"),
    },
    "TEMP_DIR": os.getenv("TEMP_DIR", "/tmp/mim-ops"),
    "RESULTS_DIR": os.getenv("RESULTS_DIR", "./results"),
}

# Create directories
os.makedirs(CONFIG["TEMP_DIR"], exist_ok=True)
os.makedirs(CONFIG["RESULTS_DIR"], exist_ok=True)

# Job state store (use Redis/DB in production)
JOBS = {}

# ═══════════════════════════════════════════════════════════
# ★ Oracle Storage Client
# ═══════════════════════════════════════════════════════════

class OracleStorageClient:
    """Oracle Object Storage client."""
    
    def __init__(self):
        self.enabled = CONFIG["ORACLE"]["use_oracle"]
        if self.enabled:
            try:
                # Initialize OCI SDK (default: uses ~/.oci/config)
                self.client = oci.object_storage.ObjectStorageClient(
                    oci.config.from_file()
                )
                self.namespace = self.client.get_namespace().data
                print(f"[Oracle] Connected to namespace: {self.namespace}")
            except Exception as e:
                print(f"[Oracle] ⚠️ Connection failed: {e}")
                self.enabled = False
    
    def upload_file(self, file_path, object_name, job_id):
        """Upload a file to Object Storage."""
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
        """Download a file from Object Storage."""
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
        """List all objects for a job."""
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
        """Clean up after a job completes."""
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
# ★ Authentication
# ═══════════════════════════════════════════════════════════

def require_api_key(f):
    """Decorator to validate the API key."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get("Authorization", "").replace("Bearer ", "")
        if not api_key or api_key != CONFIG["API_KEY"]:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function

# ═══════════════════════════════════════════════════════════
# ★ Solver Execution
# ═══════════════════════════════════════════════════════════

def run_solver(job_id, stl_path, params):
    """Run solver.py (in a separate thread)."""
    job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
    os.makedirs(job_dir, exist_ok=True)

    log_lines = []

    try:
        JOBS[job_id]["status"] = "running"
        JOBS[job_id]["start_time"] = datetime.now()
        JOBS[job_id]["log"] = []

        print(f"[Solver] Starting job {job_id}...")

        # ── Resolve absolute path to solver.py ───────────────────────
        # Search candidate paths in order:
        #   1) Same directory as this server.py
        #   2) /app/solver/solver.py  (standard Docker path)
        #   3) /app/solver.py
        server_dir  = os.path.dirname(os.path.abspath(__file__))
        repo_root   = os.path.dirname(server_dir)  # parent of api/ = repository root
        solver_candidates = [
            os.path.join(repo_root,   "solver", "solver.py"),  # ★ actual production path
            os.path.join(server_dir,  "solver", "solver.py"),
            os.path.join(server_dir,  "solver.py"),
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
                f"solver.py not found. Searched paths: {solver_candidates}"
            )
            print(f"[Solver] ❌ {err}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"]  = err
            JOBS[job_id]["log"]    = [err]
            return

        print(f"[Solver] Using solver: {solver_py}")

        # ── Ensure stl_path is an absolute path ──────────────────────
        stl_abs = os.path.abspath(stl_path) if not os.path.isabs(stl_path) \
                  else stl_path
        if not os.path.isfile(stl_abs):
            err = f"STL file not found: {stl_abs}"
            print(f"[Solver] ❌ {err}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"]  = err
            JOBS[job_id]["log"]    = [err]
            return

        # Build solver command (using absolute paths, cwd not required)
        # Use venv python (system python3 may lack packages)
        venv_python = os.path.join(repo_root, "venv", "bin", "python")
        python_exe  = venv_python if os.path.isfile(venv_python) else "python3"
        cmd = [
            python_exe, solver_py,
            "--signal_id",       job_id,
            "--stl_path",        stl_abs,          # ★ absolute path
            "--gate_x",          str(params.get("gate_x", 0.0)),
            "--gate_y",          str(params.get("gate_y", 0.0)),
            "--gate_z",          str(params.get("gate_z", 0.0)),
            "--gate_dia",        str(params.get("gate_dia", 2.0)),
            "--vel_mms",         str(params.get("vel_mms", 25.0)),
            "--etime",           str(params.get("etime", 1.0)),
            "--num_frames",      str(params.get("num_frames", 15)),
            "--mesh_res_mm",     str(params.get("mesh_res_mm", 0.5)),
            "--material",        str(params.get("material", "17-4PH")),
            "--screw_dia",       str(params.get("screw_dia", 28.0)),
            # ── Bug Fix Day 0: add previously missing parameters ──
            "--wall_friction_k", str(params.get("wall_friction_k", 3.0)),
            "--flow_decay",      str(params.get("flow_decay", 0.5)),
            "--press",           str(params.get("press", 110.0)),
            "--temp",            str(params.get("temp", 185.0)),
        ]

        import re

        process = subprocess.Popen(
            cmd,
            cwd=job_dir,                     # working directory stays as job_dir
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

                # [Issue #3] Progress parsing priority:
                # 1st: "PROGRESS:50" format (explicit output from solver.py)
                # 2nd: "50%" format (legacy compatibility)
                m = re.search(r"PROGRESS[:\s]+(\d+)", line, re.IGNORECASE)
                if m:
                    pct = min(int(m.group(1)), 99)
                    JOBS[job_id]["progress"] = pct
                else:
                    # Also handles decimal percent: "Fill: 6.7%" → captures 6
                    m2 = re.search(r"\b(\d{1,3})(?:\.\d+)?\s*%", line)
                    if m2:
                        pct2 = min(int(m2.group(1)), 99)
                        # Update only when higher than current progress (no rollback)
                        if pct2 > JOBS[job_id].get("progress", 0):
                            JOBS[job_id]["progress"] = pct2

                # [Issue #3] Immediately update error field on error keyword detection
                if any(kw in line for kw in ["MemoryError", "OOM", "Killed", "killed",
                                              "Error", "Exception", "Traceback"]):
                    JOBS[job_id]["last_error_line"] = line

            if time.time() > deadline:
                process.kill()
                JOBS[job_id]["status"] = "timeout"
                JOBS[job_id]["error"] = f"Timeout after {CONFIG['SOLVER_TIMEOUT']}s"
                JOBS[job_id]["log"] = log_lines[-100:]  # preserve last 100 lines
                print(f"[Solver] ⏱️ Timeout: {job_id}")
                return

        process.wait()

        if process.returncode != 0:
            # [Issue #3] On failure, store full log in the error field
            error_summary = JOBS[job_id].get("last_error_line", f"Solver exited with code {process.returncode}")
            JOBS[job_id]["status"] = "failed"
            JOBS[job_id]["error"] = error_summary
            JOBS[job_id]["return_code"] = process.returncode
            JOBS[job_id]["log"] = log_lines[-100:]  # preserve last 100 lines
            print(f"[Solver] ❌ Job failed with return code {process.returncode}")
            print(f"[Solver] ❌ Last error: {error_summary}")
            return
        
        # Process results
        results_file = os.path.join(job_dir, "results.json")
        if os.path.exists(results_file):
            with open(results_file) as f:
                results = json.load(f)
            JOBS[job_id]["results"] = results

            if oracle_client.enabled:
                oracle_client.upload_file(results_file, "results.json", job_id)

        # ── ★ Fix: verify actual output files before marking completed ──
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
            # Missing file means solver did not actually complete
            err = (
                "Solver exited but results.json is missing. "
                "Check the solver log."
            )
            JOBS[job_id]["status"]      = "failed"
            JOBS[job_id]["error"]       = err
            JOBS[job_id]["log"]         = log_lines[-100:]
            JOBS[job_id]["return_code"] = 0   # exit code was 0 but files are missing
            print(f"[Solver] ❌ {err}")
            return
        
        JOBS[job_id]["progress"] = 100
        JOBS[job_id]["status"] = "completed"
        JOBS[job_id]["end_time"] = datetime.now()
        JOBS[job_id]["log"] = log_lines[-50:]  # preserve last 50 lines on completion
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
    """Health check."""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "oracle_enabled": oracle_client.enabled,
    }), 200

@app.route("/api/simulate", methods=["POST"])
@require_api_key
def submit_simulation():
    """
    Submit a simulation request.

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

    The STL file is sent as multipart/form-data (key: "stl_file").
    """
    try:
        # Check STL file
        if "stl_file" not in request.files:
            return jsonify({"error": "Missing stl_file"}), 400
        
        stl_file = request.files["stl_file"]
        if not stl_file.filename.endswith(".stl"):
            return jsonify({"error": "File must be .stl"}), 400
        
        # Check file size
        stl_file.seek(0, 2)  # Seek to EOF
        file_size = stl_file.tell()
        stl_file.seek(0)  # Seek back to start
        
        if file_size > CONFIG["MAX_FILE_SIZE"]:
            return jsonify({"error": f"File too large (max {CONFIG['MAX_FILE_SIZE']/1e6}MB)"}), 413
        
        # Parse parameters
        try:
            data = request.form.to_dict()
            params = {
                "signal_id":       data.get("signal_id", "auto"),
                "gate_x":          float(data.get("gate_x", 0.0)),
                "gate_y":          float(data.get("gate_y", 0.0)),
                "gate_z":          float(data.get("gate_z", 0.0)),
                "gate_dia":        float(data.get("gate_dia", 2.0)),
                "vel_mms":         float(data.get("vel_mms", 25.0)),
                "etime":           float(data.get("etime", 1.0)),
                "num_frames":      int(data.get("num_frames", 15)),
                "mesh_res_mm":     float(data.get("mesh_res_mm", 0.5)),
                "material":        data.get("material", "17-4PH"),
                "screw_dia":       float(data.get("screw_dia", 28.0)),
                # ── Bug Fix Day 0: add previously missing parameters ──
                "wall_friction_k": float(data.get("wall_friction_k", 3.0)),
                "flow_decay":      float(data.get("flow_decay", 0.5)),
                "press":           float(data.get("press", 110.0)),
                "temp":            float(data.get("temp", 185.0)),
            }
        except (ValueError, TypeError) as e:
            return jsonify({"error": f"Invalid parameters: {e}"}), 400
        
        # Generate Job ID
        job_id = str(uuid.uuid4())[:12]
        if params["signal_id"] != "auto":
            job_id = params["signal_id"]
        
        # Job directory
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
        os.makedirs(job_dir, exist_ok=True)
        
        # Save STL file
        stl_path = os.path.join(job_dir, "input.stl")
        stl_file.save(stl_path)
        
        # Initialize job state
        JOBS[job_id] = {
            "status": "queued",
            "created_at": datetime.now().isoformat(),
            "params": params,
            "file_size_mb": file_size / 1e6,
            "progress": 0,
            "error": None,
            "log": [],
        }
        
        # Run solver (background thread)
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
            "est_time_sec": 60,  # Estimated time (depends on mesh size in practice)
        }), 202
    
    except Exception as e:
        print(f"[API] Error in /simulate: {e}")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/jobs/<job_id>", methods=["GET"])
@require_api_key
def get_job_status(job_id):
    """Query job status."""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    job = JOBS[job_id]
    
    # Calculate elapsed time
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
    
    # [Issue #3] Include error message and log for failed / error / timeout states
    if job["status"] in ("failed", "error", "timeout"):
        response["error"] = job.get("error") or "Unknown error"
        response["log"] = job.get("log", [])
        response["return_code"] = job.get("return_code")
    
    if job["status"] == "completed":
        response["results_url"] = f"/api/results/{job_id}"
    
    return jsonify(response), 200

@app.route("/api/results/<job_id>", methods=["GET"])
@require_api_key
def get_results(job_id):
    """Download results."""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    job = JOBS[job_id]
    if job["status"] != "completed":
        return jsonify({"error": f"Job status is {job['status']}",
                        "detail": job.get("error")}), 400
    
    try:
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)

        # Collect result files
        result_files = []
        for filename in ["results.json", "results.txt", "voxel_data.npz"]:
            if os.path.exists(os.path.join(job_dir, filename)):
                result_files.append(filename)

        # Check PNG count in frames directory
        frames_dir = os.path.join(job_dir, "frames")
        num_frames = 0
        if os.path.isdir(frames_dir):
            pngs = [f for f in os.listdir(frames_dir) if f.endswith(".png")]
            num_frames = len(pngs)
            if num_frames > 0:
                result_files.append(f"frames/ ({num_frames} PNGs)")
        
        # Compose result
        response_data = {
            "job_id": job_id,
            "status": "completed",
            "completed_at": job.get("end_time", datetime.now()).isoformat(),
            "files": result_files,
        }
        
        # Include results.json
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
    """Return voxel_data.npz as binary."""
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
    Return PNG files from the frames/ directory encoded as base64 JSON.
    Can be displayed directly with st.image() in Streamlit.

    Response:
    {
      "job_id": "...",
      "num_frames": 15,
      "frames": ["data:image/png;base64,...", ...]   // in order
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
    """Cancel and clean up a job."""
    if job_id not in JOBS:
        return jsonify({"error": "Job not found"}), 404
    
    try:
        job = JOBS[job_id]
        
        # Stop if running (process level)
        if job["status"] == "running":
            job["status"] = "cancelled"
        
        # Delete local files
        job_dir = os.path.join(CONFIG["RESULTS_DIR"], job_id)
        if os.path.exists(job_dir):
            import shutil
            shutil.rmtree(job_dir)
        
        # Clean up Oracle Storage
        if oracle_client.enabled:
            oracle_client.cleanup(job_id)
        
        del JOBS[job_id]
        
        return jsonify({"status": "deleted"}), 200
    
    except Exception as e:
        print(f"[API] Error in DELETE: {e}")
        return jsonify({"error": str(e)}), 500

# ═══════════════════════════════════════════════════════════
# ★ Error Handlers
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
    
    # Start Flask server
    app.run(
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", 5000)),
        debug=os.getenv("DEBUG", "false").lower() == "true"
    )
