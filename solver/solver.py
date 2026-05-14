import argparse
import os
import json
import numpy as np
import trimesh
import time
from collections import deque

# ── Day 4: materials_db import ────────────────────────────────
# solver runs from solver/ dir; materials_db.py lives in ../app/
import sys as _sys
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'app'))
try:
    from materials_db import get_material as _get_mat
    HAS_MATDB = True
    print("[Solver] materials_db loaded successfully")
except ImportError:
    HAS_MATDB = False
    print("[Solver] materials_db not found — using built-in defaults")

# ── matplotlib (headless environment support) ───────────────────
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


def parse_args():
    p = argparse.ArgumentParser(description="MIM-Ops Cloud Solver: Visual Flow Optimization")
    p.add_argument("--signal_id",       type=str,   default="manual")
    p.add_argument("--gate_pos",        type=str,   default="")
    p.add_argument("--gate_x",          type=float, default=0.0)
    p.add_argument("--gate_y",          type=float, default=0.0)
    p.add_argument("--gate_z",          type=float, default=0.0)
    p.add_argument("--gate_dia",        type=float, default=2.0)
    p.add_argument("--vel_mms",         type=float, default=25.0)
    p.add_argument("--etime",           type=float, default=10.0)
    p.add_argument("--num_frames",      type=int,   default=20)
    p.add_argument("--mesh_res_mm",     type=str,   default="0.5")
    p.add_argument("--stl_path",        type=str,   default="part.stl")
    p.add_argument("--sim_opts",        type=str,   default="")
    p.add_argument("--material",        type=str,   default="17-4PH")
    p.add_argument("--screw_dia",       type=float, default=28.0)
    p.add_argument("--viscosity",       type=float, default=4e-3)
    p.add_argument("--density",         type=float, default=7780)
    p.add_argument("--melt_temp",       type=float, default=185)
    p.add_argument("--temp",            type=float, default=185)
    p.add_argument("--press",           type=float, default=110)

    # ★ NEW parameters
    p.add_argument("--wall_friction_k", type=float, default=3.0,
                   help="Wall friction strength (0=disabled, 3=MIM default, 5+=thin rib emphasis)")
    p.add_argument("--flow_decay",      type=float, default=0.5,
                   help="Distance-based flow decay coefficient (0=disabled, 0.5=default, 1.0=strong)")

    args = p.parse_args()

    # Parse "0.5,28.0" format
    if isinstance(args.mesh_res_mm, str):
        if "," in args.mesh_res_mm:
            parts = args.mesh_res_mm.split(",")
            args.mesh_res_mm = float(parts[0].strip())
            args.screw_dia   = float(parts[1].strip())
        else:
            args.mesh_res_mm = float(args.mesh_res_mm)

    # Parse gate_pos
    if args.gate_pos.strip():
        try:
            parts = [v.strip() for v in args.gate_pos.split(",")]
            if len(parts) >= 3:
                args.gate_x, args.gate_y, args.gate_z = float(parts[0]), float(parts[1]), float(parts[2])
            if len(parts) >= 4:
                args.gate_dia = float(parts[3])
            print(f"[Solver] gate_pos -> x={args.gate_x}, y={args.gate_y}, z={args.gate_z}, dia={args.gate_dia}")
        except Exception as e:
            print(f"[Solver] gate_pos parse error: {e}")

    # Parse sim_opts
    if args.sim_opts.strip():
        try:
            parts = [v.strip() for v in args.sim_opts.split(",")]
            if len(parts) >= 1 and parts[0]: args.material   = parts[0]
            if len(parts) >= 2 and parts[1]: args.num_frames = int(parts[1])
            print(f"[Solver] sim_opts -> material={args.material}, frames={args.num_frames}, "
                  f"res={args.mesh_res_mm}, screw={args.screw_dia}mm")
        except Exception as e:
            print(f"[Solver] sim_opts parse error: {e}")

    return args


# ════════════════════════════════════════════════════
# RAM Estimation
# ════════════════════════════════════════════════════

def estimate_memory_gb(mesh, res_mm):
    bounds = mesh.bounds
    bb = np.maximum(bounds[1] - bounds[0], 1e-6)
    est_voxels = max(
        int(np.ceil(bb[0] / res_mm)) *
        int(np.ceil(bb[1] / res_mm)) *
        int(np.ceil(bb[2] / res_mm)), 1
    )
    BYTES_PER_VOXEL = 800
    return est_voxels, (est_voxels * BYTES_PER_VOXEL) / (1024 ** 3)


def recommend_resolution(mesh, max_ram_gb=16.0):
    safe_ram = max_ram_gb * 0.75
    for res in [2.0, 1.5, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3]:
        _, ram = estimate_memory_gb(mesh, res)
        if ram <= safe_ram:
            return res, ram
    return 2.0, None


# ════════════════════════════════════════════════════
# ★ Core function: Dijkstra with multi-source gate + wall friction
# ════════════════════════════════════════════════════

def compute_dijkstra_weights(all_coords, start_indices, res, wall_friction_k=0.0):
    """
    Changes:
      1. start_indices: single int → ndarray (multi-source gate support)
      2. If wall_friction_k > 0, wall friction weights are applied
         - Detect surface voxels (neighbors < 26) → compute dist_to_wall via BFS
         - edge_weight *= (1 + k / (dist_to_wall + eps))
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import shortest_path
    from scipy.spatial import cKDTree

    total = len(all_coords)
    print(f"[Solver] Building sparse graph ({total:,} voxels)...", flush=True)
    print("PROGRESS:27", flush=True)

    neighbor_radius = res * 1.85
    tree = cKDTree(all_coords.astype(np.float64))
    pairs = tree.query_pairs(r=neighbor_radius, output_type='ndarray')  # (E, 2)
    print(f"[Solver] {len(pairs):,} neighbor pairs found", flush=True)
    print("PROGRESS:35", flush=True)

    if len(pairs) == 0:
        print("[Solver] ⚠️ No neighbor pairs — returning uniform weights", flush=True)
        return np.zeros(total, dtype=np.float32)

    # ── edge distances ──────────────────────────────────────────
    diffs = (all_coords[pairs[:, 0]].astype(np.float64)
             - all_coords[pairs[:, 1]].astype(np.float64))
    edge_dists = np.sqrt((diffs ** 2).sum(axis=1)).astype(np.float32)
    del diffs
    print("PROGRESS:38", flush=True)

    # ── ★ wall friction ─────────────────────────────────────────
    if wall_friction_k > 0:
        print(f"[Solver] Computing wall friction (k={wall_friction_k})...", flush=True)

        # 1) Surface voxels: neighbor count < 26  (fully-interior voxels have exactly 26)
        cnt = (np.bincount(pairs[:, 0], minlength=total)
               + np.bincount(pairs[:, 1], minlength=total))
        surface_idx = np.where(cnt < 26)[0]
        print(f"[Solver]   Surface voxels: {len(surface_idx):,}", flush=True)

        # 2) Build CSR adjacency array (for BFS)
        src_b = np.concatenate([pairs[:, 0], pairs[:, 1]])
        dst_b = np.concatenate([pairs[:, 1], pairs[:, 0]])
        order = np.argsort(src_b, kind='stable')
        src_b, dst_b = src_b[order], dst_b[order]
        indptr = np.searchsorted(src_b, np.arange(total + 1))
        del src_b, order

        # 3) Multi-source BFS → dist_to_wall (integer in voxel units)
        dist_w = np.full(total, -1, dtype=np.int32)
        bfs_q  = deque()
        for si in surface_idx:
            dist_w[si] = 0
            bfs_q.append(int(si))

        while bfs_q:
            nd   = bfs_q.popleft()
            d_nd = dist_w[nd] + 1
            for nb in dst_b[indptr[nd]: indptr[nd + 1]]:
                if dist_w[nb] == -1:
                    dist_w[nb] = d_nd
                    bfs_q.append(int(nb))

        # Convert to mm (negative = isolated voxel → treat as 0)
        dist_w_mm = np.where(dist_w >= 0, dist_w, 0).astype(np.float32) * res
        del dist_w, dst_b, indptr, surface_idx, cnt

        # 4) Average dist_to_wall per edge → apply friction coefficient
        #    friction = 1 + k / (d_avg + eps)
        #    eps = res/2 : voxels directly on the wall (d=0) retain finite friction
        eps   = res * 0.5
        d_avg = (dist_w_mm[pairs[:, 0]] + dist_w_mm[pairs[:, 1]]) * 0.5
        friction = (1.0 + wall_friction_k / (d_avg + eps)).astype(np.float32)
        edge_dists = edge_dists * friction
        del dist_w_mm, d_avg, friction
        print("[Solver]   Wall friction applied.", flush=True)

    print("PROGRESS:40", flush=True)

    # ── CSR graph ───────────────────────────────────────────────
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    data = np.concatenate([edge_dists, edge_dists])
    graph = csr_matrix((data, (rows, cols)), shape=(total, total), dtype=np.float32)
    del pairs, edge_dists, rows, cols, data
    print("[Solver] Running scipy Dijkstra (C)...", flush=True)
    print("PROGRESS:43", flush=True)

    # ── ★ Multi-source Dijkstra ────────────────────────────────
    #    1 start index → 1D result, multiple → 2D → min(axis=0)
    if len(start_indices) == 1:
        dist_arr = shortest_path(
            graph, method='D', directed=False,
            indices=int(start_indices[0]),
            return_predecessors=False,
        ).astype(np.float32)
    else:
        dm = shortest_path(
            graph, method='D', directed=False,
            indices=start_indices,
            return_predecessors=False,
        )                                   # shape: (n_sources, total)
        dist_arr = dm.min(axis=0).astype(np.float32)
        del dm

    del graph
    print("[Solver] Dijkstra complete.", flush=True)
    print("PROGRESS:50", flush=True)

    finite_mask = np.isfinite(dist_arr)
    max_d = float(dist_arr[finite_mask].max()) if finite_mask.any() else 1.0
    dist_arr[~finite_mask] = max_d
    return dist_arr / max_d


# ════════════════════════════════════════════════════
# Day 1: Pressure Distribution Calculation
# ════════════════════════════════════════════════════

def calc_pressure(norm_weights: np.ndarray,
                  P_gate_mpa: float = 80.0) -> np.ndarray:
    """
    Invert BFS fill-order weights into a pressure distribution.
    Gate (weight=0) = max pressure, flow front (weight=1) = 0 pressure.
    """
    pressure = P_gate_mpa * (1.0 - norm_weights)
    return pressure.astype(np.float32)


# ════════════════════════════════════════════════════
# Day 2: Weld Line Detection
# ════════════════════════════════════════════════════

def detect_weld_lines(
    coords: np.ndarray,
    norm_weights: np.ndarray,
    res: float,
    time_tolerance: float = 0.05,
) -> np.ndarray:
    """
    Voxels where opposing flow fronts meet at nearly the same time = weld lines.
    < 100K voxels: full scan / >= 100K: 10% sampling
    Returns: weld_flags (N,) bool
    """
    from scipy.spatial import cKDTree

    total_n  = len(coords)
    gate_idx = int(np.argmin(norm_weights))
    gate_pos = coords[gate_idx]
    tree     = cKDTree(coords)
    weld_flags = np.zeros(total_n, dtype=bool)

    # Full scan if < 100K voxels, 10% sampling otherwise
    if total_n < 100_000:
        check_idx = np.arange(total_n)
        print(f"[Solver] Weld line: full scan ({total_n:,} voxels)", flush=True)
    else:
        sample_size = total_n // 10
        check_idx   = np.random.choice(total_n, size=sample_size, replace=False)
        print(f"[Solver] Weld line: 10% sampling ({sample_size:,} / {total_n:,} voxels)", flush=True)

    for i in check_idx:
        neighbors = tree.query_ball_point(coords[i], r=res * 1.9)
        vec_i  = coords[i] - gate_pos
        norm_i = np.linalg.norm(vec_i) + 1e-8
        vec_i  /= norm_i

        for j in neighbors:
            if j <= i:
                continue
            if abs(norm_weights[i] - norm_weights[j]) > time_tolerance:
                continue
            vec_j  = coords[j] - gate_pos
            norm_j = np.linalg.norm(vec_j) + 1e-8
            vec_j  /= norm_j
            if np.dot(vec_i, vec_j) < -0.3:   # approx. 107 degrees opposite direction
                weld_flags[i] = True
                weld_flags[j] = True

    return weld_flags


# ════════════════════════════════════════════════════
# Day 3: Air Trap Detection + Vent Recommendation
# ════════════════════════════════════════════════════

def detect_airtraps(
    coords: np.ndarray,
    norm_weights: np.ndarray,
    res: float,
    late_fill_threshold: float = 0.90,
) -> np.ndarray:
    """
    Surface-adjacent voxels among the latest-filled ones (norm_weight > threshold)
    are air trap candidates.
    Returns: airtrap_flags (N,) bool
    """
    from scipy.spatial import cKDTree

    late_mask = norm_weights > late_fill_threshold
    if not late_mask.any():
        return np.zeros(len(coords), dtype=bool)

    tree  = cKDTree(coords)
    pairs = tree.query_pairs(r=res * 1.85)
    cnt   = np.zeros(len(coords), dtype=int)
    for i, j in pairs:
        cnt[i] += 1
        cnt[j] += 1
    # Surface voxel if fewer than 26 neighbors
    surface_mask   = cnt < 26
    airtrap_flags  = late_mask & surface_mask
    return airtrap_flags


def recommend_vents(
    coords: np.ndarray,
    airtrap_flags: np.ndarray,
    top_n: int = 5,
) -> list:
    """Air trap cluster centroids → recommended vent positions (greedy max-spread)."""
    if not airtrap_flags.any():
        return []
    at_coords = coords[airtrap_flags]
    top_n     = min(top_n, len(at_coords))
    vents     = [at_coords[0]]
    for _ in range(top_n - 1):
        dists = np.array([
            min(np.linalg.norm(c - v) for v in vents)
            for c in at_coords
        ])
        vents.append(at_coords[np.argmax(dists)])
    return [v.tolist() for v in vents]


# ════════════════════════════════════════════════════
# Day 4: Temperature Distribution + Cooling Time
# ════════════════════════════════════════════════════

def calc_temperature(
    norm_weights: np.ndarray,
    material_name: str,
    T_inject_C: float | None = None,
) -> np.ndarray:
    """
    Fill-order-based temperature distribution estimate.
    Gate (weight=0) = T_inject (hottest), flow front (weight=1) = Tmold (coolest).
    Linear interpolation — first-order approximation of heat transfer.
    """
    if HAS_MATDB:
        mat = _get_mat(material_name)
    else:
        mat = {"Tmelt_C": 1400.0, "Tmold_C": 50.0, "T_eject_C": 120.0,
               "Cp_J_kgK": 480.0, "k_W_mK": 18.0}

    T_high = T_inject_C if T_inject_C is not None else mat["Tmelt_C"]
    T_low  = mat["Tmold_C"]

    temp_map = T_high - (T_high - T_low) * norm_weights
    return temp_map.astype(np.float32)


def calc_cooling_time(
    material_name: str,
    T_inject_C: float,
    thickness_mm: float,
) -> float:
    """
    Cooling time estimate based on Throne equation (injection molding approximation).
    tc = (h^2) / (pi^2 * alpha) * ln(4/pi * (T_inj - T_mold) / (T_eject - T_mold))
    alpha = k / (rho * Cp)  — thermal diffusivity (mm^2/s)
    """
    import math
    if HAS_MATDB:
        mat = _get_mat(material_name)
    else:
        mat = {"Tmelt_C": 1400.0, "Tmold_C": 50.0, "T_eject_C": 120.0,
               "Cp_J_kgK": 480.0, "k_W_mK": 18.0, "rho_kg_m3": 7800.0}

    alpha = mat["k_W_mK"] / (mat["rho_kg_m3"] * mat["Cp_J_kgK"]) * 1e6  # mm^2/s
    T_m   = mat["Tmold_C"]
    T_e   = mat["T_eject_C"]
    denom = T_e - T_m
    if denom <= 0:
        return 0.0
    numer = T_inject_C - T_m
    if numer <= 0 or numer <= denom:
        return 0.0
    h  = thickness_mm
    tc = (h ** 2) / (np.pi ** 2 * alpha) * math.log((4.0 / np.pi) * (numer / denom))
    return round(max(tc, 0.0), 2)


def save_visual_frame(coords, display_weights, threshold_ratio, frame_idx,
                      phys_time_label, fill_pct, out_dir):
    """
    display_weights: visualization weights with flow_decay post-processing applied
                     (separate from norm_weights — npz stores the raw values)
    """
    mask = display_weights <= threshold_ratio
    filled_coords = coords[mask]

    if len(filled_coords) == 0:
        filled_coords = coords[:1]
        color_vals = np.array([0.0])
    else:
        color_vals = display_weights[mask]
        max_c = max(threshold_ratio, 1e-6)
        color_vals = np.clip(color_vals / max_c, 0.0, 1.0)

    fig = plt.figure(figsize=(10, 7), facecolor="#111111")
    ax  = fig.add_subplot(111, projection="3d", facecolor="#111111")

    scatter = ax.scatter(
        filled_coords[:, 0], filled_coords[:, 1], filled_coords[:, 2],
        c=1.0 - color_vals, cmap="Blues", s=4, alpha=0.85, depthshade=False,
    )

    cbar = fig.colorbar(scatter, ax=ax, shrink=0.5, pad=0.05)
    cbar.set_label("Flow Distance (gate→front)", color="white", fontsize=9)
    cbar.ax.yaxis.set_tick_params(color="white")
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color="white")

    ax.set_xlabel("X (mm)", color="white", fontsize=9)
    ax.set_ylabel("Y (mm)", color="white", fontsize=9)
    ax.set_zlabel("Z (mm)", color="white", fontsize=9)
    ax.tick_params(colors="white")
    for pane in (ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane):
        pane.fill = False
        pane.set_edgecolor("#333333")

    ax.set_title(
        f"MIM Fill: {fill_pct:.1f}%  |  Physical Time: {phys_time_label}  |  Frame {frame_idx + 1}",
        color="white", fontsize=12, pad=12,
    )

    all_ranges = coords.max(axis=0) - coords.min(axis=0)
    all_mins   = coords.min(axis=0)
    max_range  = all_ranges.max() / 2.0
    mid        = all_mins + all_ranges / 2.0
    ax.set_xlim(mid[0] - max_range, mid[0] + max_range)
    ax.set_ylim(mid[1] - max_range, mid[1] + max_range)
    ax.set_zlim(mid[2] - max_range, mid[2] + max_range)

    img_path = os.path.join(out_dir, f"frame_{frame_idx:03d}.png")
    plt.savefig(img_path, dpi=100, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return img_path


def _export_vtk(all_coords, norm_weights, res):
    try:
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk
    except ImportError:
        print("[Solver] vtk package not found — skipping VTK output (pip install vtk)")
        return

    os.makedirs("VTK", exist_ok=True)
    h = res / 2.0

    grid = vtk.vtkUnstructuredGrid()
    pts  = vtk.vtkPoints()
    pts.SetNumberOfPoints(len(all_coords) * 8)

    for i, (cx, cy, cz) in enumerate(all_coords):
        base = i * 8
        corners = [
            (cx-h, cy-h, cz-h), (cx+h, cy-h, cz-h),
            (cx+h, cy+h, cz-h), (cx-h, cy+h, cz-h),
            (cx-h, cy-h, cz+h), (cx+h, cy-h, cz+h),
            (cx+h, cy+h, cz+h), (cx-h, cy+h, cz+h),
        ]
        for j, (x, y, z) in enumerate(corners):
            pts.SetPoint(base + j, x, y, z)
        hx = vtk.vtkHexahedron()
        for j in range(8):
            hx.GetPointIds().SetId(j, base + j)
        grid.InsertNextCell(hx.GetCellType(), hx.GetPointIds())

    grid.SetPoints(pts)
    flow_arr = numpy_to_vtk(norm_weights, deep=True)
    flow_arr.SetName("flow_distance")
    grid.GetCellData().AddArray(flow_arr)
    grid.GetCellData().SetActiveScalars("flow_distance")
    for ai, an in enumerate(("voxel_x", "voxel_y", "voxel_z")):
        ca = numpy_to_vtk(all_coords[:, ai].astype(np.float32), deep=True)
        ca.SetName(an)
        grid.GetCellData().AddArray(ca)

    w = vtk.vtkXMLUnstructuredGridWriter()
    w.SetFileName("VTK/internal.vtu")
    w.SetInputData(grid)
    w.Write()
    print(f"[Solver] ✅ VTK saved: VTK/internal.vtu ({len(all_coords)} cells)")


def main():
    args = parse_args()
    start_wall_time = time.time()

    print(f"[Solver] STL: {args.stl_path}", flush=True)
    print(f"[Solver] Gate: ({args.gate_x}, {args.gate_y}, {args.gate_z}), dia={args.gate_dia}mm", flush=True)
    print(f"[Solver] wall_friction_k={args.wall_friction_k}, flow_decay={args.flow_decay}", flush=True)
    print("PROGRESS:2", flush=True)

    # 1. Load STL
    print("[Solver] Loading STL mesh...", flush=True)
    mesh = trimesh.load(args.stl_path)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(
            [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        )
    print(f"[Solver] Mesh: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces", flush=True)
    print("PROGRESS:5", flush=True)

    res = args.mesh_res_mm
    est_voxels_at_res, est_ram_at_res = estimate_memory_gb(mesh, res)
    rec_16, _ = recommend_resolution(mesh, max_ram_gb=16.0)
    rec_24, _ = recommend_resolution(mesh, max_ram_gb=24.0)
    print(f"[Solver] Resolution {res}mm → est. voxels: {est_voxels_at_res:,}  est. RAM: {est_ram_at_res:.2f} GB", flush=True)
    if est_ram_at_res > 12.0:
        print(f"[Solver] ⚠️  Warning: {res}mm resolution est. RAM {est_ram_at_res:.1f}GB → recommended {rec_16:.1f}mm")

    print(f"[Solver] Starting voxelization at {res}mm...", flush=True)
    print("PROGRESS:8", flush=True)

    try:
        import gc
        bb_min_v, bb_max_v = mesh.bounds

        xs = np.arange(bb_min_v[0] + res/2, bb_max_v[0], res, dtype=np.float32)
        ys = np.arange(bb_min_v[1] + res/2, bb_max_v[1], res, dtype=np.float32)
        zs = np.arange(bb_min_v[2] + res/2, bb_max_v[2], res, dtype=np.float32)
        grid_total = len(xs) * len(ys) * len(zs)
        print(f"[Solver] Grid: {len(xs)}×{len(ys)}×{len(zs)} = {grid_total:,}", flush=True)
        print("PROGRESS:10", flush=True)

        if grid_total > 250_000_000:
            raise MemoryError(f"Grid too large ({grid_total:,}). Increase resolution.")

        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
        raw_coords = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        del gx, gy, gz, xs, ys, zs
        gc.collect()
        print("PROGRESS:13", flush=True)

        # ── contains fallback chain (original retained) ──────────
        def _contains_chunked_trimesh(pts):
            try:
                import trimesh.ray.ray_triangle as _rt
                intersector = _rt.RayMeshIntersector(mesh)
                intersector.contains_points(pts[:1])
            except (ModuleNotFoundError, ImportError):
                raise
            CHUNK = 50_000
            out = []
            for ci in range(0, len(pts), CHUNK):
                out.append(intersector.contains_points(pts[ci: ci+CHUNK]))
                print(f"PROGRESS:{min(13 + int((ci+CHUNK)/len(pts)*11), 24)}", flush=True)
            return np.concatenate(out)

        def _contains_pysdf(pts):
            import pysdf
            sdf = pysdf.SDF(mesh.vertices, mesh.faces)
            CHUNK = 100_000
            out = []
            for ci in range(0, len(pts), CHUNK):
                out.append(sdf(pts[ci: ci+CHUNK]) < 0)
                print(f"PROGRESS:{min(13 + int((ci+CHUNK)/len(pts)*11), 24)}", flush=True)
            return np.concatenate(out)

        def _contains_winding(pts):
            verts = mesh.vertices.astype(np.float64)
            faces = mesh.faces
            v0 = verts[faces[:,0]]; v1 = verts[faces[:,1]]; v2 = verts[faces[:,2]]
            e1 = v1 - v0; e2 = v2 - v0
            CHUNK = 5_000
            out   = np.zeros(len(pts), dtype=bool)
            ray_d = np.array([0.0, 0.0, 1.0])
            t_xmin = np.minimum(v0[:,0], np.minimum(v1[:,0], v2[:,0]))
            t_xmax = np.maximum(v0[:,0], np.maximum(v1[:,0], v2[:,0]))
            t_ymin = np.minimum(v0[:,1], np.minimum(v1[:,1], v2[:,1]))
            t_ymax = np.maximum(v0[:,1], np.maximum(v1[:,1], v2[:,1]))
            for ci in range(0, len(pts), CHUNK):
                ch    = pts[ci: ci+CHUNK].astype(np.float64)
                count = np.zeros(len(ch), dtype=np.int32)
                for ti in range(len(faces)):
                    mask = ((ch[:,0]>=t_xmin[ti])&(ch[:,0]<=t_xmax[ti])&
                            (ch[:,1]>=t_ymin[ti])&(ch[:,1]<=t_ymax[ti]))
                    if not mask.any(): continue
                    p   = ch[mask]
                    h   = np.cross(ray_d, e2[ti]); det = e1[ti].dot(h)
                    if abs(det) < 1e-10: continue
                    inv = 1.0/det; s = p - v0[ti]; u = inv*(s@h)
                    ok  = (u>=0)&(u<=1)
                    if not ok.any(): continue
                    q   = np.cross(s[ok], e1[ti]); v_ = inv*(q@ray_d)
                    ok2 = (v_>=0)&(u[ok]+v_<=1)
                    if not ok2.any(): continue
                    t_  = inv*(q[ok2]@e2[ti]); hit = t_ > 1e-10
                    count[np.where(mask)[0][ok][ok2][hit]] += 1
                out[ci: ci+CHUNK] = (count % 2) == 1
                print(f"PROGRESS:{min(13+int((ci+CHUNK)/len(pts)*11),24)}", flush=True)
            return out

        inside_mask = None
        try:
            print("[Solver] Trying trimesh ray-casting...", flush=True)
            inside_mask = _contains_chunked_trimesh(raw_coords)
            print("[Solver] ✅ trimesh succeeded", flush=True)
        except Exception as e1:
            print(f"[Solver] ⚠️ trimesh failed ({e1}), trying pysdf...", flush=True)
        if inside_mask is None:
            try:
                inside_mask = _contains_pysdf(raw_coords)
                print("[Solver] ✅ pysdf succeeded", flush=True)
            except Exception as e2:
                print(f"[Solver] ⚠️ pysdf failed ({e2}), numpy winding...", flush=True)
        if inside_mask is None:
            print("[Solver] Using numpy winding-number...", flush=True)
            inside_mask = _contains_winding(raw_coords)
            print("[Solver] ✅ numpy winding succeeded", flush=True)

        raw_coords = raw_coords[inside_mask]
        del inside_mask
        gc.collect()
        print(f"[Solver] Voxels (inside): {len(raw_coords):,}", flush=True)
        print("PROGRESS:16", flush=True)

    except MemoryError as me:
        print(f"[Solver] ❌ OOM: {me}", flush=True); raise
    except Exception as e:
        print(f"[Solver] ❌ Voxelization failed: {e}", flush=True)
        import traceback; traceback.print_exc(); return

    all_coords = raw_coords.astype(np.float32)
    del raw_coords
    gc.collect()
    print(f"[Solver] Voxels ready: {len(all_coords):,}", flush=True)
    print("PROGRESS:25", flush=True)

    total_voxels = len(all_coords)

    # 2. Fill time
    vol_mm3    = total_voxels * (res ** 3)
    screw_area = np.pi * (args.screw_dia / 2) ** 2
    flow_rate  = screw_area * args.vel_mms if args.vel_mms > 0 else 1.0
    theo_fill_time = vol_mm3 / flow_rate
    print(f"[Solver] Vol={vol_mm3:.1f}mm³ | Screw ø{args.screw_dia}mm | "
          f"Flow={flow_rate:.0f}mm³/s | FillTime={theo_fill_time:.3f}s", flush=True)

    # 3. ★ Gate multi-source — all voxels within gate_dia radius as start points
    gate_pos = np.array([args.gate_x, args.gate_y, args.gate_z], dtype=np.float32)
    bb_min, bb_max = all_coords.min(axis=0), all_coords.max(axis=0)

    gate_in_range = np.all(gate_pos >= bb_min - res) and np.all(gate_pos <= bb_max + res)
    if not gate_in_range:
        z_min_mask = all_coords[:, 2] < bb_min[2] + res * 2
        gate_pos   = all_coords[z_min_mask].mean(axis=0)
        print(f"[Solver] Gate out of range → fallback bottom-center: {gate_pos.round(2)}", flush=True)
    else:
        print(f"[Solver] Gate accepted: {gate_pos.round(3)}", flush=True)

    dists_to_gate = np.linalg.norm(all_coords - gate_pos, axis=1)
    gate_radius   = args.gate_dia / 2.0
    gate_mask_idx = np.where(dists_to_gate <= gate_radius)[0]

    if len(gate_mask_idx) == 0:
        # Gate diameter smaller than resolution: use single nearest voxel
        gate_mask_idx = np.array([int(np.argmin(dists_to_gate))])
        print(f"[Solver] Gate dia < res → single start voxel fallback", flush=True)

    print(f"[Solver] ★ Gate voxels (multi-source): {len(gate_mask_idx)}", flush=True)
    print("PROGRESS:26", flush=True)

    # 4. Dijkstra (multi-source + wall friction)
    norm_weights = compute_dijkstra_weights(
        all_coords, gate_mask_idx, res,
        wall_friction_k=args.wall_friction_k,
    )
    print("PROGRESS:50", flush=True)

    # 5. ★ Flow decay post-processing — only display_weights are transformed
    #    Physics: v = v0 / (1 + decay*d) → time ∝ d + decay*d²
    #    norm_weights are preserved as-is (written to npz and JSON)
    k_decay = args.flow_decay
    if k_decay > 0:
        display_weights = (norm_weights + k_decay * norm_weights ** 2) / (1.0 + k_decay)
        print(f"[Solver] Flow decay applied (k={k_decay}): "
              f"max display weight = {display_weights.max():.4f}", flush=True)
    else:
        display_weights = norm_weights
        print("[Solver] Flow decay disabled (k=0)", flush=True)

    # 6. Animation frames
    result_dir  = os.path.dirname(os.path.abspath(args.stl_path))
    frames_dir  = os.path.join(result_dir, "frames")
    os.makedirs(frames_dir, exist_ok=True)
    num_frames  = args.num_frames
    print(f"[Solver] Generating {num_frames} frames...", flush=True)

    for f in range(num_frames):
        visual_ratio = (f + 1) / num_frames
        fill_pct     = visual_ratio * 100.0
        phys_time    = visual_ratio * theo_fill_time
        phys_label   = f"{phys_time*1000:.1f} ms" if phys_time < 1.0 else f"{phys_time:.3f} s"

        save_visual_frame(
            coords=all_coords,
            display_weights=display_weights,   # ★ use decay-applied weights
            threshold_ratio=visual_ratio,
            frame_idx=f,
            phys_time_label=phys_label,
            fill_pct=fill_pct,
            out_dir=frames_dir,
        )
        frame_pct = 50 + int(((f + 1) / num_frames) * 45)
        print(f"PROGRESS:{frame_pct}", flush=True)
        print(f"  Frame {f+1}/{num_frames} | Fill: {fill_pct:.1f}% | t={phys_label}", flush=True)

    # 7. Save results
    elapsed = time.time() - start_wall_time

    results = {
        "Signal ID":            args.signal_id,
        "Material":             args.material,
        "Total Voxels":         total_voxels,
        "num_voxels":           total_voxels,
        "Part Volume (mm3)":    round(vol_mm3, 2),
        "Gate Dia (mm)":        args.gate_dia,
        "Gate Pos (mm)":        [round(float(v), 3) for v in gate_pos],
        "Gate Voxels":          int(len(gate_mask_idx)),       # ★ NEW
        "Injection Vel (mm/s)": args.vel_mms,
        "max_vel_mms":          args.vel_mms,
        "Theo Fill Time (s)":   round(theo_fill_time, 4),
        "theo_fill_time":       round(theo_fill_time, 4),
        "res_mm":               res,
        "Num Frames":           num_frames,
        "Mesh Res (mm)":        res,
        "Solver Time (s)":      round(elapsed, 2),
        "Status":               "Success",
        "Est RAM (GB)":         round(est_ram_at_res, 3),
        "Rec Res 16GB (mm)":    rec_16,
        "Rec Res 24GB (mm)":    rec_24,
        "wall_friction_k":      args.wall_friction_k,          # ★ NEW
        "flow_decay":           args.flow_decay,               # ★ NEW
        "Note": (
            "Frames use display_weights (flow_decay applied). "
            "norm_weights in npz are raw Dijkstra output."
        ),
        "voxel_data_file": "voxel_data.npz",
    }

    # ── Day 1~3 analysis: after results dict, before JSON save ────
    # Day 1: Pressure calculation
    pressure_map = calc_pressure(norm_weights, P_gate_mpa=args.press)

    # Day 2: Weld line detection
    print("[Solver] Detecting weld lines...", flush=True)
    weld_flags = detect_weld_lines(all_coords, norm_weights, res)
    print(f"[Solver] Weld line voxels: {int(weld_flags.sum()):,}", flush=True)

    # Day 3: Air trap detection + vent recommendation
    print("[Solver] Detecting airtraps...", flush=True)
    airtrap_flags  = detect_airtraps(all_coords, norm_weights, res)
    vent_positions = recommend_vents(all_coords, airtrap_flags, top_n=5)
    print(f"[Solver] Airtrap voxels: {int(airtrap_flags.sum()):,} | Vents: {len(vent_positions)}", flush=True)

    # Day 4: Temperature distribution + cooling time
    print("[Solver] Calculating temperature distribution...", flush=True)
    temp_map = calc_temperature(norm_weights, args.material, T_inject_C=args.temp)
    print(f"[Solver] Temp range: {temp_map.min():.1f} ~ {temp_map.max():.1f} °C", flush=True)

    # Average wall thickness estimate (volume / surface area approximation)
    vol_mm3_val = total_voxels * (res ** 3)
    try:
        from scipy.spatial import cKDTree as _cKDTreeThick
        _tree_thick  = _cKDTreeThick(all_coords)
        _pairs_thick = _tree_thick.query_pairs(r=res * 1.85)
        _cnt_thick   = np.zeros(len(all_coords), dtype=int)
        for _pi, _pj in _pairs_thick:
            _cnt_thick[_pi] += 1
            _cnt_thick[_pj] += 1
        surf_voxels_thick = int((_cnt_thick < 26).sum())
        avg_thick_mm = max(vol_mm3_val / (surf_voxels_thick * res ** 2 + 1e-6), res)
        del _tree_thick, _pairs_thick, _cnt_thick
    except Exception:
        avg_thick_mm = 3.0  # fallback default
    print(f"[Solver] Avg wall thickness estimate: {avg_thick_mm:.2f} mm", flush=True)

    cooling_time = calc_cooling_time(args.material, args.temp, avg_thick_mm)
    print(f"[Solver] Estimated cooling time: {cooling_time} s", flush=True)

    # Surface voxel detection (for visualization — displays part shape in UI background)
    print("[Solver] Computing surface mask for visualization...", flush=True)
    from scipy.spatial import cKDTree as _cKDTree
    _tree  = _cKDTree(all_coords)
    _pairs = _tree.query_pairs(r=res * 1.85)
    _cnt   = np.zeros(len(all_coords), dtype=int)
    for _i, _j in _pairs:
        _cnt[_i] += 1
        _cnt[_j] += 1
    surface_mask = (_cnt < 26).astype(np.uint8)
    print(f"[Solver] Surface voxels: {int(surface_mask.sum()):,}", flush=True)

    # Append Day 3 results to results dict
    results["airtrap_count"]  = int(airtrap_flags.sum())
    results["vent_positions"] = vent_positions

    # Append Day 4 results to results dict
    results["T_inject_C"]    = float(args.temp)
    results["cooling_time_s"] = cooling_time
    if HAS_MATDB:
        mat_props = _get_mat(args.material)
        results["T_eject_C"] = mat_props["T_eject_C"]
        results["Tmold_C"]   = mat_props["Tmold_C"]
    else:
        results["T_eject_C"] = 120.0
        results["Tmold_C"]   = 50.0

    results_json_path = os.path.join(result_dir, "results.json")
    with open(results_json_path, "w") as fh:
        json.dump(results, fh, indent=4)
    print(f"[Solver] ✅ results.json: {results_json_path}", flush=True)

    npz_path = os.path.join(result_dir, "voxel_data.npz")
    np.savez_compressed(
        npz_path,
        coords=all_coords.astype(np.float32),
        weights=norm_weights.astype(np.float32),
        display_weights=display_weights.astype(np.float32),  # ★ retained
        pressure=pressure_map,                                # ★ Day 1 retained
        weld=weld_flags.astype(np.uint8),                    # ★ Day 2 retained
        airtrap=airtrap_flags.astype(np.uint8),              # ★ Day 3 retained
        surface=surface_mask,                                 # ★ Day 3 retained
        temp=temp_map,                                        # ★ Day 4 NEW
    )
    print(f"[Solver] ✅ voxel_data.npz: {npz_path} ({total_voxels} voxels)", flush=True)

    results_txt_path = os.path.join(result_dir, "results.txt")
    with open(results_txt_path, "w") as fh:
        for k, v in results.items():
            fh.write(f"{k}: {v}\n")

    os.makedirs(os.path.join(result_dir, "frames"), exist_ok=True)
    _export_vtk(all_coords, norm_weights, res)

    print(f"[Solver] Done in {elapsed:.1f}s. {num_frames} frames → {frames_dir}/", flush=True)
    print("PROGRESS:100", flush=True)


if __name__ == "__main__":
    main()
