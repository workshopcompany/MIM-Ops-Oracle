# Day 8 — Integration Test & Oracle Cloud Deployment Checklist

> **Environment**
> - VM IP: `132.145.187.95`
> - Deploy path: `/opt/mim-ops/MIM-Ops-Oracle/` (**NOT** `/home/ubuntu/`)
> - Services: `mim-ops-api` (port 5000) · `mim-ops-streamlit` (port 8501)
> - Restart command: `sudo systemctl restart mim-ops-api mim-ops-streamlit`

---

## Step 0 — Pre-flight: Local Git Push

```bash
cd C:\Users\lg\MIM-Ops-Oracle

# 1. Verify changed files
git status
git diff solver/solver.py

# 2. Stage all Day 1–7 changes
git add api/server.py \
        solver/solver.py \
        app/streamlit_app.py \
        app/materials_db.py \
        deploy.sh

# 3. Commit with descriptive message
git commit -m "Day 1-7: pressure/weld/airtrap/temp/cooling/shrinkage/deformation"

# 4. Push
git push origin main
```

**Pass criteria:** `git push` exits 0, GitHub shows latest commit.

---

## Step 1 — Deploy to Oracle VM

```bash
# Option A — one-click script (recommended)
chmod +x deploy.sh
./deploy.sh

# Option B — manual
ssh -i ~/.ssh/your-key.pem ubuntu@132.145.187.95
cd /opt/mim-ops/MIM-Ops-Oracle
git pull origin main
sudo systemctl restart mim-ops-api mim-ops-streamlit
```

---

## Step 2 — Service Health Check

```bash
# API health endpoint
curl http://132.145.187.95:5000/health
# Expected: {"status": "OK", "message": "MIM-Ops API is running"}

# Port check
sudo netstat -tlnp | grep -E "5000|8501"
# Expected: both ports LISTEN

# Service status
sudo systemctl status mim-ops-api --no-pager
sudo systemctl status mim-ops-streamlit --no-pager
# Expected: active (running)
```

| Check | Command | Expected |
|-------|---------|----------|
| API health | `curl http://132.145.187.95:5000/health` | `{"status":"OK"...}` |
| API port | `sudo lsof -i :5000` | process listening |
| UI port | `sudo lsof -i :8501` | process listening |
| API service | `systemctl is-active mim-ops-api` | `active` |
| UI service | `systemctl is-active mim-ops-streamlit` | `active` |

---

## Step 3 — End-to-End Functional Tests

### 3-1. Simulation Run

- [ ] Open `http://132.145.187.95:8501` in browser
- [ ] Upload an STL file in **[Simulation]** tab
- [ ] Set material (e.g. `CATAMOLD-17-4PH`) and injection temperature
- [ ] Click **Run Simulation**
- [ ] Verify `job_id` appears and progress bar reaches 100%
- [ ] Verify `results.json` contains all expected keys (see table below)

**Expected `results.json` keys (Day 1–7 cumulative):**

```json
{
  "max_pressure_MPa":       <float>,
  "weld_line_count":        <int>,
  "airtrap_count":          <int>,
  "vent_positions":         [[x,y,z], ...],
  "T_inject_C":             <float>,
  "T_eject_C":              <float>,
  "Tmold_C":                <float>,
  "cooling_time_s":         <float>,
  "avg_thickness_mm":       <float>,
  "max_thickness_mm":       <float>,
  "min_thickness_mm":       <float>,
  "max_cooling_time_s":     <float>,
  "mean_cooling_time_s":    <float>,
  "cooling_hotspot_mm":     [x, y, z],
  "max_shrinkage_pct":      <float>,
  "mean_shrinkage_pct":     <float>,
  "min_shrinkage_pct":      <float>,
  "sintering_shrinkage_pct":<float>,
  "max_deform_um":          <float>,
  "mean_deform_um":         <float>,
  "max_deform_coord_mm":    [x, y, z]
}
```

### 3-2. voxel_data.npz Fields

```bash
# On the VM, verify all npz fields exist
python3 - <<'EOF'
import numpy as np, glob, os
npz_files = glob.glob("/opt/mim-ops/MIM-Ops-Oracle/results/*/voxel_data.npz")
f = np.load(sorted(npz_files)[-1])
required = ["coords","weights","display_weights","pressure","weld",
            "airtrap","surface","temp","thickness","cooling_time_map",
            "shrinkage","deform_vectors"]
missing = [k for k in required if k not in f]
print("Missing fields:", missing if missing else "None — all OK ✅")
print("Present fields:", list(f.keys()))
EOF
```

| npz field | Day added | Type |
|-----------|-----------|------|
| `coords` | Day 0 | float32 (N,3) |
| `weights` | Day 0 | float32 (N,) |
| `display_weights` | Day 0 | float32 (N,) |
| `pressure` | Day 1 | float32 (N,) |
| `weld` | Day 2 | uint8 (N,) |
| `airtrap` | Day 3 | uint8 (N,) |
| `surface` | Day 3 | bool (N,) |
| `temp` | Day 4 | float32 (N,) |
| `thickness` | Day 5 | float32 (N,) |
| `cooling_time_map` | Day 5 | float32 (N,) |
| `shrinkage` | Day 6 | float32 (N,) |
| `deform_vectors` | Day 7 | float32 (N,3) |

---

### 3-3. Tab Regression Tests

#### tab1 — Simulation
- [ ] STL upload works
- [ ] Material dropdown shows all 35 materials
- [ ] Progress bar runs to 100%

#### tab2 — Material Library
- [ ] All materials listed
- [ ] Property values display correctly

#### tab3 — Results
- [ ] `display_weights` 3D viewer renders
- [ ] Download result button works

#### tab4 — Settings
- [ ] Parameters save correctly

#### tab_phase1 — Pressure · Weld · AirTrap
- [ ] **Pressure** 3D viewer renders (blue→red gradient)
- [ ] **Weld line** count metric displays
- [ ] **Air trap** count metric displays
- [ ] Vent positions table shows coordinates

#### tab_phase2 — Temp · Cooling
- [ ] Temperature 3D viewer renders
- [ ] Temperature histogram shows bell-ish distribution
- [ ] Temperature vs Fill Order scatter shows downward trend
- [ ] Cooling summary table shows `cooling_time_s`
- [ ] **Wall thickness** 3D viewer renders (Day 5)
- [ ] **Cooling time map** 3D viewer renders (Day 5)
- [ ] Cooling hotspot warning appears with coordinates

#### tab_phase3 — Shrinkage · Deform
- [ ] Max / Mean shrinkage metrics display
- [ ] **Max deformation (μm)** metric displays (Day 7)
- [ ] Maximum deformation warning shows X/Y/Z + direction vector
- [ ] Shrinkage 3D viewer renders
- [ ] **Deformation magnitude 3D viewer** renders (Day 7)
- [ ] **Deformation quiver (XY)** scatter renders (Day 7)
- [ ] Shrinkage vs Pressure scatter renders
- [ ] Shrinkage vs Temperature scatter renders
- [ ] Total shrinkage reference table shows injection + sintering sum
- [ ] High-shrinkage zone warning OR success message appears

---

## Step 4 — Log Verification (no ERROR lines)

```bash
# On VM — check last 50 lines for errors
sudo journalctl -u mim-ops-api -n 50 | grep -iE "error|exception|traceback" | head -20
sudo journalctl -u mim-ops-streamlit -n 50 | grep -iE "error|exception|traceback" | head -20
# Expected: no output (clean logs)

# Confirm Day 5–7 solver output lines appear in a recent job
sudo journalctl -u mim-ops-api --since "1 hour ago" | grep -E "Day[567]|thickness|deform|shrinkage"
```

---

## Step 5 — Rollback Procedure (if needed)

```bash
# On VM — revert to previous commit
ssh -i ~/.ssh/your-key.pem ubuntu@132.145.187.95
cd /opt/mim-ops/MIM-Ops-Oracle

git log --oneline -5          # find the good commit hash
git checkout <GOOD_HASH> -- solver/solver.py app/streamlit_app.py

sudo systemctl restart mim-ops-api mim-ops-streamlit
```

---

## Quick Reference — VM Commands

```bash
# SSH
ssh -i ~/.ssh/your-key.pem ubuntu@132.145.187.95

# Deploy
cd /opt/mim-ops/MIM-Ops-Oracle && git pull origin main
sudo systemctl restart mim-ops-api mim-ops-streamlit

# Status
sudo systemctl status mim-ops-api mim-ops-streamlit --no-pager

# Live logs
sudo journalctl -fu mim-ops-api
sudo journalctl -fu mim-ops-streamlit

# Port check
sudo netstat -tlnp | grep -E "5000|8501"

# Health
curl http://localhost:5000/health

# Force kill + restart (if hung)
sudo systemctl kill mim-ops-api && sudo systemctl start mim-ops-api

# pip install new dependency
sudo -u mim-ops /opt/mim-ops/MIM-Ops-Oracle/venv/bin/pip install <package>

# Git hard reset (last resort)
git fetch origin && git reset --hard origin/main
```

---

## Day 8 Sign-off Checklist

| Item | Status |
|------|--------|
| `git push` to GitHub complete | ☐ |
| `./deploy.sh` exits 0 | ☐ |
| API health returns OK | ☐ |
| Both systemd services active | ☐ |
| tab_phase1 all 3 sections render | ☐ |
| tab_phase2 cooling + thickness renders | ☐ |
| tab_phase3 shrinkage + deformation renders | ☐ |
| tab1~tab4 no regression | ☐ |
| No ERROR in journalctl logs | ☐ |

> All 9 items checked → **Day 8 complete. Deployment done. ✅**
