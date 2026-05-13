import argparse
import os
import json
import numpy as np
import trimesh
import time
from collections import deque

# ── matplotlib (헤드리스 환경 대응) ──────────────────────────
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

    # ★ 신규 파라미터
    p.add_argument("--wall_friction_k", type=float, default=3.0,
                   help="벽면 마찰 강도 (0=비활성, 3=MIM 기본, 5+=얇은 리브 강조)")
    p.add_argument("--flow_decay",      type=float, default=0.5,
                   help="거리 기반 속도 저하 계수 (0=비활성, 0.5=기본, 1.0=강함)")

    args = p.parse_args()

    # "0.5,28.0" 형태 분리
    if isinstance(args.mesh_res_mm, str):
        if "," in args.mesh_res_mm:
            parts = args.mesh_res_mm.split(",")
            args.mesh_res_mm = float(parts[0].strip())
            args.screw_dia   = float(parts[1].strip())
        else:
            args.mesh_res_mm = float(args.mesh_res_mm)

    # gate_pos 파싱
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

    # sim_opts 파싱
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
# RAM 예측
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
# ★ 핵심 함수: Dijkstra with multi-source gate + wall friction
# ════════════════════════════════════════════════════

def compute_dijkstra_weights(all_coords, start_indices, res, wall_friction_k=0.0):
    """
    변경사항:
      1. start_indices: 단일 int → ndarray (multi-source gate 지원)
      2. wall_friction_k > 0 이면 벽면 마찰 가중치 적용
         - 표면 복셀(이웃 < 26개) 탐지 → BFS로 dist_to_wall 계산
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

    # ── 엣지 거리 ──────────────────────────────────────────────
    diffs = (all_coords[pairs[:, 0]].astype(np.float64)
             - all_coords[pairs[:, 1]].astype(np.float64))
    edge_dists = np.sqrt((diffs ** 2).sum(axis=1)).astype(np.float32)
    del diffs
    print("PROGRESS:38", flush=True)

    # ── ★ 벽면 마찰 ────────────────────────────────────────────
    if wall_friction_k > 0:
        print(f"[Solver] Computing wall friction (k={wall_friction_k})...", flush=True)

        # 1) 표면 복셀: 이웃 수 < 26  (내부 완전 연결 복셀은 정확히 26개)
        cnt = (np.bincount(pairs[:, 0], minlength=total)
               + np.bincount(pairs[:, 1], minlength=total))
        surface_idx = np.where(cnt < 26)[0]
        print(f"[Solver]   Surface voxels: {len(surface_idx):,}", flush=True)

        # 2) CSR 인접 배열 구축 (BFS 용)
        src_b = np.concatenate([pairs[:, 0], pairs[:, 1]])
        dst_b = np.concatenate([pairs[:, 1], pairs[:, 0]])
        order = np.argsort(src_b, kind='stable')
        src_b, dst_b = src_b[order], dst_b[order]
        indptr = np.searchsorted(src_b, np.arange(total + 1))
        del src_b, order

        # 3) Multi-source BFS → dist_to_wall (복셀 단위 정수)
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

        # mm 변환 (음수 = 고립 복셀 → 0 처리)
        dist_w_mm = np.where(dist_w >= 0, dist_w, 0).astype(np.float32) * res
        del dist_w, dst_b, indptr, surface_idx, cnt

        # 4) 엣지별 평균 dist_to_wall → 마찰 계수 적용
        #    friction = 1 + k / (d_avg + eps)
        #    eps = res/2 : 벽 바로 위 복셀(d=0)도 유한한 마찰 유지
        eps   = res * 0.5
        d_avg = (dist_w_mm[pairs[:, 0]] + dist_w_mm[pairs[:, 1]]) * 0.5
        friction = (1.0 + wall_friction_k / (d_avg + eps)).astype(np.float32)
        edge_dists = edge_dists * friction
        del dist_w_mm, d_avg, friction
        print("[Solver]   Wall friction applied.", flush=True)

    print("PROGRESS:40", flush=True)

    # ── CSR 그래프 ─────────────────────────────────────────────
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    data = np.concatenate([edge_dists, edge_dists])
    graph = csr_matrix((data, (rows, cols)), shape=(total, total), dtype=np.float32)
    del pairs, edge_dists, rows, cols, data
    print("[Solver] Running scipy Dijkstra (C)...", flush=True)
    print("PROGRESS:43", flush=True)

    # ── ★ Multi-source Dijkstra ────────────────────────────────
    #    start_indices 가 1개면 1D 반환, 복수면 2D → min(axis=0)
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
# Day 1: 압력분포 계산
# ════════════════════════════════════════════════════

def calc_pressure(norm_weights: np.ndarray,
                  P_gate_mpa: float = 80.0) -> np.ndarray:
    """
    BFS 가중치(충전 순서)로 압력 분포 역산.
    게이트(weight=0) = 최고압, 유동선단(weight=1) = 0압
    """
    pressure = P_gate_mpa * (1.0 - norm_weights)
    return pressure.astype(np.float32)


def save_visual_frame(coords, display_weights, threshold_ratio, frame_idx,
                      phys_time_label, fill_pct, out_dir):
    """
    display_weights: flow_decay 후처리가 적용된 시각용 가중치
                     (norm_weights 와 별도 — npz 저장에는 원본 사용)
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
        print("[Solver] vtk 패키지 없음 — VTK 출력 건너뜀 (pip install vtk)")
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
    print(f"[Solver] ✅ VTK 저장: VTK/internal.vtu ({len(all_coords)} cells)")


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
    print(f"[Solver] 해상도 {res}mm → 예상 복셀: {est_voxels_at_res:,}  예상 RAM: {est_ram_at_res:.2f} GB", flush=True)
    if est_ram_at_res > 12.0:
        print(f"[Solver] ⚠️  경고: {res}mm 해상도 예상 RAM {est_ram_at_res:.1f}GB → 권장 {rec_16:.1f}mm")

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

        # ── contains 폴백 체인 (기존 유지) ──────────────────────
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

    # 3. ★ Gate multi-source — gate_dia 반경 내 복셀 전부 시작점
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
        # 게이트 직경이 해상도보다 작을 때: 가장 가까운 1개
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

    # 5. ★ Flow decay 후처리 — 애니메이션용 display_weights만 변환
    #    물리 근거: v = v0 / (1 + decay*d) → time ∝ d + decay*d²
    #    norm_weights는 원본 보존 (npz, JSON에 기록)
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
            display_weights=display_weights,   # ★ decay 적용 가중치 사용
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
        "Gate Voxels":          int(len(gate_mask_idx)),       # ★ 추가
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
        "wall_friction_k":      args.wall_friction_k,          # ★ 추가
        "flow_decay":           args.flow_decay,               # ★ 추가
        "Note": (
            "Frames use display_weights (flow_decay applied). "
            "norm_weights in npz are raw Dijkstra output."
        ),
        "voxel_data_file": "voxel_data.npz",
    }

    results_json_path = os.path.join(result_dir, "results.json")
    with open(results_json_path, "w") as fh:
        json.dump(results, fh, indent=4)
    print(f"[Solver] ✅ results.json: {results_json_path}", flush=True)

    # npz: norm_weights (원본) + display_weights 모두 저장
    # Day 1: pressure 필드 추가
    pressure_map = calc_pressure(norm_weights, P_gate_mpa=args.press)

    npz_path = os.path.join(result_dir, "voxel_data.npz")
    np.savez_compressed(
        npz_path,
        coords=all_coords.astype(np.float32),
        weights=norm_weights.astype(np.float32),
        display_weights=display_weights.astype(np.float32),  # ★ 기존 유지
        pressure=pressure_map,                                # ★ Day 1 신규
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
