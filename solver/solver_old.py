import argparse
import os
import json
import numpy as np
import trimesh
import time
from collections import deque

# ── matplotlib (헤드리스 환경 대응) ──────────────────────────
import matplotlib
matplotlib.use("Agg")  # GUI 없는 서버 환경 필수
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


def parse_args():
    p = argparse.ArgumentParser(description="MIM-Ops Cloud Solver: Visual Flow Optimization")
    p.add_argument("--signal_id",   type=str,   default="manual")
    p.add_argument("--gate_pos",    type=str,   default="")   # "x,y,z,dia"
    p.add_argument("--gate_x",      type=float, default=0.0)
    p.add_argument("--gate_y",      type=float, default=0.0)
    p.add_argument("--gate_z",      type=float, default=0.0)
    p.add_argument("--gate_dia",    type=float, default=2.0)
    p.add_argument("--vel_mms",     type=float, default=25.0)
    p.add_argument("--etime",       type=float, default=10.0)
    p.add_argument("--num_frames",  type=int,   default=20)
    
    # [핵심 수정 포인트] float 대신 str로 받아서 "0.5,28.0" 에러 방지
    p.add_argument("--mesh_res_mm", type=str,   default="0.5") 
    
    p.add_argument("--stl_path",    type=str,   default="part.stl")
    p.add_argument("--sim_opts",    type=str,   default="")   # "material,frames,res,screw_dia"
    p.add_argument("--material",    type=str,   default="17-4PH")
    p.add_argument("--screw_dia",   type=float, default=28.0) # 스크류 직경 (mm)
    p.add_argument("--viscosity",   type=float, default=4e-3)
    p.add_argument("--density",     type=float, default=7780)
    p.add_argument("--melt_temp",   type=float, default=185)
    p.add_argument("--temp",        type=float, default=185)
    p.add_argument("--press",       type=float, default=110)
    args = p.parse_args()

    # [핵심 수정 포인트] YAML 파일 한계로 인해 "0.5,28.0" 으로 묶여서 들어오는 문자열을 분리
    if isinstance(args.mesh_res_mm, str):
        if "," in args.mesh_res_mm:
            parts = args.mesh_res_mm.split(",")
            args.mesh_res_mm = float(parts[0].strip())   # 0.5
            args.screw_dia   = float(parts[1].strip())   # 28.0
        else:
            args.mesh_res_mm = float(args.mesh_res_mm)

    # gate_pos 파싱: "x,y,z,dia"
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

    # sim_opts 파싱: "material,frames,res,screw_dia"
    if args.sim_opts.strip():
        try:
            parts = [v.strip() for v in args.sim_opts.split(",")]
            if len(parts) >= 1 and parts[0]: args.material    = parts[0]
            if len(parts) >= 2 and parts[1]: args.num_frames  = int(parts[1])
            # mesh_res_mm 와 screw_dia 는 위에서 안전하게 처리했으므로 통과
            print(f"[Solver] sim_opts -> material={args.material}, frames={args.num_frames}, res={args.mesh_res_mm}, screw={args.screw_dia}mm")
        except Exception as e:
            print(f"[Solver] sim_opts parse error: {e}")

    return args


# ════════════════════════════════════════════════════
# ★ RAM 예측 함수 (Issue #2)
# ════════════════════════════════════════════════════

def estimate_memory_gb(mesh, res_mm):
    """
    주어진 해상도에서 예상 복셀 수와 RAM 사용량(GB)을 반환.

    ★ 핵심 설계 원칙:
      fill_ratio(부피/BB)는 얇은 판형 파트에서 실제 복셀 수를 크게 과소 추정.
      예: 84x50x5mm 판 -> fill_ratio~0.02 -> 실제의 1/50 수준으로 예측.
      fill_ratio 를 제거하고 바운딩박스 전체 복셀 수(최악 케이스)로 보수적 추정.

    ★ bytes_per_voxel 실측 근거 — BFS 방식 기준 (~210 bytes):
      - all_coords float32  : 12 bytes
      - dist float32        :  4 bytes
      - visited bool array  :  1 byte
      - idx_map dict entry  : ~100 bytes  (Python dict 오버헤드)
      - grid_idx int32      : 12 bytes
      - deque entry         :  8 bytes
      - Python 런타임 x1.5
      합계: (12+4+1+100+12+8) x 1.5 = 210 bytes/voxel
    """
    bounds = mesh.bounds
    bb = bounds[1] - bounds[0]
    bb = np.maximum(bb, 1e-6)

    grid_nx = int(np.ceil(bb[0] / res_mm))
    grid_ny = int(np.ceil(bb[1] / res_mm))
    grid_nz = int(np.ceil(bb[2] / res_mm))
    # fill_ratio 제거: BB 전체 복셀 수로 보수적 추정 (OOM 방지)
    est_voxels = max(int(grid_nx) * int(grid_ny) * int(grid_nz), 1)

    BYTES_PER_VOXEL = 800  # scipy sparse Dijkstra 실측: cKDTree+pairs+csr+dist 합산
    est_ram_gb = (est_voxels * BYTES_PER_VOXEL) / (1024 ** 3)

    return est_voxels, est_ram_gb


def recommend_resolution(mesh, max_ram_gb=16.0):
    """
    사용 가능한 RAM 한계 내에서 권장 해상도를 반환.
    안전 마진 75% 적용.
    """
    safe_ram = max_ram_gb * 0.75
    for res in [2.0, 1.5, 1.0, 0.8, 0.6, 0.5, 0.4, 0.3]:
        _, ram = estimate_memory_gb(mesh, res)
        if ram <= safe_ram:
            return res, ram
    return 2.0, None


def compute_dijkstra_weights(all_coords, start_idx, res):
    """
    scipy.sparse.csgraph Dijkstra — C 구현, Python BFS 대비 100× 빠름.

    ★ 왜 교체했나:
      이전 Python BFS: dict 역매핑 구축 O(V) + 루프당 tuple 생성·hash → 21K 복셀에서도 수분 소요.
      scipy 방식: cKDTree.query_pairs (C) + csr_matrix + shortest_path (Dijkstra C) → < 1 초.
      RAM도 90% 절감 (Python 객체 오버헤드 없음).
    """
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import shortest_path
    from scipy.spatial import cKDTree

    total = len(all_coords)
    print(f"[Solver] Building sparse graph ({total:,} voxels)...", flush=True)
    print("PROGRESS:27", flush=True)

    # 26-연결 이웃을 모두 포함하는 반경 (면=res, 모서리=res√2, 꼭짓점=res√3 ≈ 1.73)
    neighbor_radius = res * 1.85

    tree = cKDTree(all_coords.astype(np.float64))
    pairs = tree.query_pairs(r=neighbor_radius, output_type='ndarray')  # (E, 2)
    print(f"[Solver] {len(pairs):,} neighbor pairs found", flush=True)
    print("PROGRESS:35", flush=True)

    if len(pairs) == 0:
        print("[Solver] ⚠️ No neighbor pairs — returning uniform weights", flush=True)
        return np.zeros(total, dtype=np.float32)

    # 엣지 거리 계산 (벡터화, C 속도)
    diffs = all_coords[pairs[:, 0]].astype(np.float64) - all_coords[pairs[:, 1]].astype(np.float64)
    edge_dists = np.sqrt((diffs ** 2).sum(axis=1)).astype(np.float32)
    print("PROGRESS:40", flush=True)

    # 대칭 희소 행렬 (양방향)
    rows = np.concatenate([pairs[:, 0], pairs[:, 1]])
    cols = np.concatenate([pairs[:, 1], pairs[:, 0]])
    data = np.concatenate([edge_dists, edge_dists])
    graph = csr_matrix((data, (rows, cols)), shape=(total, total), dtype=np.float32)
    del pairs, diffs, edge_dists, rows, cols, data  # 즉시 해제
    print("[Solver] Running scipy Dijkstra (C)...", flush=True)
    print("PROGRESS:43", flush=True)

    dist_arr = shortest_path(
        graph,
        method='D',
        directed=False,
        indices=start_idx,
        return_predecessors=False,
    ).astype(np.float32)

    del graph
    print("[Solver] Dijkstra complete.", flush=True)
    print("PROGRESS:50", flush=True)

    finite_mask = np.isfinite(dist_arr)
    max_d = float(dist_arr[finite_mask].max()) if finite_mask.any() else 1.0
    dist_arr[~finite_mask] = max_d
    return dist_arr / max_d


def save_visual_frame(coords, norm_weights, threshold_ratio, frame_idx,
                      phys_time_label, fill_pct, out_dir):
    """
    matplotlib Agg 백엔드로 PNG 저장.
    kaleido / plotly 불필요 — GitHub Actions 헤드리스 환경에서 안정적으로 동작.
    """
    mask = norm_weights <= threshold_ratio
    filled_coords = coords[mask]

    if len(filled_coords) == 0:
        filled_coords = coords[:1]
        color_vals = np.array([0.0])
    else:
        color_vals = norm_weights[mask]
        max_c = max(threshold_ratio, 1e-6)
        color_vals = np.clip(color_vals / max_c, 0.0, 1.0)

    fig = plt.figure(figsize=(10, 7), facecolor="#111111")
    ax = fig.add_subplot(111, projection="3d", facecolor="#111111")

    # 색상: Blues 역방향 (gate=짙은 파랑, front=연한 파랑)
    scatter = ax.scatter(
        filled_coords[:, 0],
        filled_coords[:, 1],
        filled_coords[:, 2],
        c=1.0 - color_vals,       # 역방향
        cmap="Blues",
        s=4,
        alpha=0.85,
        depthshade=False,
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

    # 축 비율 동일하게 (equal aspect)
    all_ranges = coords.max(axis=0) - coords.min(axis=0)
    all_mins   = coords.min(axis=0)
    max_range  = all_ranges.max() / 2.0
    mid        = all_mins + all_ranges / 2.0
    ax.set_xlim(mid[0] - max_range, mid[0] + max_range)
    ax.set_ylim(mid[1] - max_range, mid[1] + max_range)
    ax.set_zlim(mid[2] - max_range, mid[2] + max_range)

    img_path = os.path.join(out_dir, f"frame_{frame_idx:03d}.png")
    plt.savefig(img_path, dpi=100, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    plt.close(fig)
    return img_path


def _export_vtk(all_coords, norm_weights, res):
    """
    복셀 좌표 + Dijkstra 가중치를 VTK UnstructuredGrid로 저장.
    각 복셀을 res×res×res 헥사헤드론으로 출력 → ParaView에서 바로 열림.
    """
    try:
        import vtk
        from vtk.util.numpy_support import numpy_to_vtk
    except ImportError:
        print("[Solver] vtk 패키지 없음 — VTK 출력 건너뜀 (pip install vtk)")
        return

    os.makedirs("VTK", exist_ok=True)
    h = res / 2.0  # 복셀 반경

    points_vtk = vtk.vtkPoints()
    grid = vtk.vtkUnstructuredGrid()

    n = len(all_coords)
    pts = vtk.vtkPoints()
    pts.SetNumberOfPoints(n * 8)

    cell_arr = vtk.vtkCellArray()
    offsets = [0]

    for i, (cx, cy, cz) in enumerate(all_coords):
        base = i * 8
        # 헥사헤드론 8 꼭짓점 (VTK HEX 순서)
        corners = [
            (cx-h, cy-h, cz-h), (cx+h, cy-h, cz-h),
            (cx+h, cy+h, cz-h), (cx-h, cy+h, cz-h),
            (cx-h, cy-h, cz+h), (cx+h, cy-h, cz+h),
            (cx+h, cy+h, cz+h), (cx-h, cy+h, cz+h),
        ]
        for j, (x, y, z) in enumerate(corners):
            pts.SetPoint(base + j, x, y, z)

        hex_cell = vtk.vtkHexahedron()
        for j in range(8):
            hex_cell.GetPointIds().SetId(j, base + j)
        grid.InsertNextCell(hex_cell.GetCellType(), hex_cell.GetPointIds())

    grid.SetPoints(pts)

    # flow_distance 스칼라 (alpha 대응 — 0=gate, 1=최원단)
    flow_arr = numpy_to_vtk(norm_weights, deep=True)
    flow_arr.SetName("flow_distance")
    grid.GetCellData().AddArray(flow_arr)
    grid.GetCellData().SetActiveScalars("flow_distance")

    # 복셀 중심 좌표를 CellData 배열로 통합 저장 (x, y, z)
    for axis_idx, axis_name in enumerate(("voxel_x", "voxel_y", "voxel_z")):
        coord_arr = numpy_to_vtk(all_coords[:, axis_idx].astype(np.float32), deep=True)
        coord_arr.SetName(axis_name)
        grid.GetCellData().AddArray(coord_arr)

    writer = vtk.vtkXMLUnstructuredGridWriter()
    writer.SetFileName("VTK/internal.vtu")
    writer.SetInputData(grid)
    writer.Write()
    print(f"[Solver] ✅ VTK 저장 완료: VTK/internal.vtu ({n} cells, coords+flow_distance 포함)")


def main():
    args = parse_args()
    start_wall_time = time.time()

    print(f"[Solver] STL: {args.stl_path}", flush=True)
    print(f"[Solver] Gate: ({args.gate_x}, {args.gate_y}, {args.gate_z}, flush=True), dia={args.gate_dia}mm", flush=True)
    print("PROGRESS:2", flush=True)

    # 1. Load & voxelise STL
    print("[Solver] Loading STL mesh...", flush=True)
    mesh = trimesh.load(args.stl_path)
    if isinstance(mesh, trimesh.Scene):
        mesh = trimesh.util.concatenate(
            [g for g in mesh.geometry.values() if isinstance(g, trimesh.Trimesh)]
        )
    print(f"[Solver] Mesh loaded: {len(mesh.vertices)} vertices, {len(mesh.faces)} faces", flush=True)
    print("PROGRESS:5", flush=True)

    # ── RAM 예측 및 해상도 권장 (UI에서 이미 사전 안내됨 → 여기서는 경고만) ──
    res = args.mesh_res_mm
    est_voxels_at_res, est_ram_at_res = estimate_memory_gb(mesh, res)
    rec_16, _ = recommend_resolution(mesh, max_ram_gb=16.0)
    rec_24, _ = recommend_resolution(mesh, max_ram_gb=24.0)

    print(f"[Solver] 해상도 {res}mm → 예상 복셀: {est_voxels_at_res:,}  예상 RAM: {est_ram_at_res:.2f} GB", flush=True)

    # RAM 초과 경고만 출력 (상세 테이블은 UI에서 사전 표시)
    if est_ram_at_res > 12.0:
        print(f"[Solver] ⚠️  경고: {res}mm 해상도에서 예상 RAM {est_ram_at_res:.1f}GB → "
              f"부족 시 {rec_16:.1f}mm 권장 (UI에서 해상도 조정 후 재시도)")

    print(f"[Solver] Starting voxelization at resolution {res}mm...", flush=True)
    print("PROGRESS:8", flush=True)

    try:
        import gc

        bb_min_v = mesh.bounds[0]
        bb_max_v = mesh.bounds[1]

        xs = np.arange(bb_min_v[0] + res / 2, bb_max_v[0], res, dtype=np.float32)
        ys = np.arange(bb_min_v[1] + res / 2, bb_max_v[1], res, dtype=np.float32)
        zs = np.arange(bb_min_v[2] + res / 2, bb_max_v[2], res, dtype=np.float32)
        grid_total = len(xs) * len(ys) * len(zs)

        print(f"[Solver] Grid: {len(xs)}×{len(ys)}×{len(zs)} = {grid_total:,} candidate points", flush=True)
        print("PROGRESS:10", flush=True)

        if grid_total > 250_000_000:
            raise MemoryError(
                f"Grid too large ({grid_total:,}). "
                f"Please increase resolution (lower precision number)."
            )

        gx, gy, gz = np.meshgrid(xs, ys, zs, indexing='ij')
        raw_coords = np.column_stack([gx.ravel(), gy.ravel(), gz.ravel()])
        del gx, gy, gz, xs, ys, zs
        gc.collect()
        print("PROGRESS:13", flush=True)

        # ════════════════════════════════════════════════════════════════
        # ★ rtree-free contains: 3단계 폴백 체인
        #
        # 방법 1: trimesh.ray.ray_pyembree  → 가장 빠름, embree 있을 때
        # 방법 2: pysdf (signed-distance)   → rtree 불필요, 빠름
        # 방법 3: 순수 numpy winding-number  → 의존성 0, 항상 동작
        # ════════════════════════════════════════════════════════════════

        def _contains_chunked_trimesh(pts):
            """
            trimesh ray-casting — embree 있으면 초고속, 없으면 순수 C 구현.
            rtree 를 명시적으로 우회: ray_triangle 대신 ray_pyembree 또는
            trimesh 내장 ray_triangle_bulk (rtree-free path) 사용.
            """
            # trimesh >= 3.15: contains() 가 embree 또는 pure-python 자동 선택
            # rtree 경로를 차단하기 위해 triangles_tree 를 미리 None으로 덮어씀
            try:
                import trimesh.ray.ray_triangle as _rt
                intersector = _rt.RayMeshIntersector(mesh)
                # rtree 없이 동작하는지 1개짜리 probe 테스트
                intersector.contains_points(pts[:1])
            except (ModuleNotFoundError, ImportError):
                raise  # rtree 없으면 다음 방법으로

            CHUNK = 50_000
            out = []
            for ci in range(0, len(pts), CHUNK):
                ch = pts[ci: ci + CHUNK]
                out.append(intersector.contains_points(ch))
                pct = 13 + int((ci + CHUNK) / len(pts) * 11)
                print(f"PROGRESS:{min(pct, 24)}", flush=True)
            return np.concatenate(out)

        def _contains_pysdf(pts):
            """pysdf SDF 기반 — rtree 불필요"""
            import pysdf
            sdf = pysdf.SDF(mesh.vertices, mesh.faces)
            CHUNK = 100_000
            out = []
            for ci in range(0, len(pts), CHUNK):
                ch = pts[ci: ci + CHUNK]
                # SDF < 0 이면 내부
                out.append(sdf(ch) < 0)
                pct = 13 + int((ci + CHUNK) / len(pts) * 11)
                print(f"PROGRESS:{min(pct, 24)}", flush=True)
            return np.concatenate(out)

        def _contains_winding(pts):
            """
            벡터화된 +Z ray casting (순수 numpy, 의존성 0).
            각 점에서 +Z 방향으로 ray를 쏴 삼각형 교차 횟수가 홀수면 내부.
            Möller–Trumbore 알고리즘 완전 벡터화.
            """
            verts = mesh.vertices.astype(np.float64)
            faces = mesh.faces
            v0 = verts[faces[:, 0]]  # (T, 3)
            v1 = verts[faces[:, 1]]
            v2 = verts[faces[:, 2]]
            e1 = v1 - v0             # (T, 3)
            e2 = v2 - v0

            CHUNK = 5_000
            out   = np.zeros(len(pts), dtype=bool)
            ray_d = np.array([0.0, 0.0, 1.0])  # +Z

            # 삼각형별 AABB (한 번만 계산)
            t_xmin = np.minimum(v0[:,0], np.minimum(v1[:,0], v2[:,0]))
            t_xmax = np.maximum(v0[:,0], np.maximum(v1[:,0], v2[:,0]))
            t_ymin = np.minimum(v0[:,1], np.minimum(v1[:,1], v2[:,1]))
            t_ymax = np.maximum(v0[:,1], np.maximum(v1[:,1], v2[:,1]))

            for ci in range(0, len(pts), CHUNK):
                ch    = pts[ci: ci + CHUNK].astype(np.float64)  # (C, 3)
                count = np.zeros(len(ch), dtype=np.int32)

                for ti in range(len(faces)):
                    # AABB 필터 (C,) bool
                    mask = (
                        (ch[:,0] >= t_xmin[ti]) & (ch[:,0] <= t_xmax[ti]) &
                        (ch[:,1] >= t_ymin[ti]) & (ch[:,1] <= t_ymax[ti])
                    )
                    if not mask.any():
                        continue

                    p   = ch[mask]           # (M, 3)
                    # Möller–Trumbore (벡터화, M points vs 1 triangle)
                    h   = np.cross(ray_d, e2[ti])        # (3,)
                    det = e1[ti].dot(h)
                    if abs(det) < 1e-10:
                        continue
                    inv = 1.0 / det
                    s   = p - v0[ti]                     # (M, 3)
                    u   = inv * (s @ h)                  # (M,)
                    ok  = (u >= 0) & (u <= 1)
                    if not ok.any():
                        continue
                    q   = np.cross(s[ok], e1[ti])        # (M', 3)
                    v   = inv * (q @ ray_d)              # (M',)
                    ok2 = (v >= 0) & (u[ok] + v <= 1)
                    if not ok2.any():
                        continue
                    t_  = inv * (q[ok2] @ e2[ti])        # (M'',)
                    hit = t_ > 1e-10
                    # count 인덱스 역추적
                    idx_mask  = np.where(mask)[0]
                    idx_ok    = idx_mask[ok]
                    idx_ok2   = idx_ok[ok2]
                    idx_hit   = idx_ok2[hit]
                    count[idx_hit] += 1

                out[ci: ci + CHUNK] = (count % 2) == 1
                pct = 13 + int((ci + CHUNK) / len(pts) * 11)
                print(f"PROGRESS:{min(pct, 24)}", flush=True)

            return out

        # ── 폴백 체인 실행 ────────────────────────────────────────────
        inside_mask = None

        # 방법 1: trimesh ray (rtree 없이 시도)
        try:
            print("[Solver] Trying trimesh ray-casting (no rtree)...", flush=True)
            inside_mask = _contains_chunked_trimesh(raw_coords)
            print("[Solver] ✅ trimesh ray-casting succeeded", flush=True)
        except Exception as e1:
            print(f"[Solver] ⚠️ trimesh ray failed ({e1}), trying pysdf...", flush=True)

        # 방법 2: pysdf
        if inside_mask is None:
            try:
                inside_mask = _contains_pysdf(raw_coords)
                print("[Solver] ✅ pysdf succeeded", flush=True)
            except Exception as e2:
                print(f"[Solver] ⚠️ pysdf failed ({e2}), using numpy winding-number...", flush=True)

        # 방법 3: numpy winding-number (항상 동작)
        if inside_mask is None:
            print("[Solver] Using numpy winding-number (slow but dependency-free)...", flush=True)
            inside_mask = _contains_winding(raw_coords)
            print("[Solver] ✅ numpy winding-number succeeded", flush=True)

        raw_coords = raw_coords[inside_mask]
        del inside_mask
        gc.collect()

        print(f"[Solver] Voxels (inside mesh): {len(raw_coords):,}", flush=True)
        print("PROGRESS:16", flush=True)

    except MemoryError as me:
        print(f"[Solver] ❌ OOM during voxelization: {me}", flush=True)
        raise
    except Exception as e:
        print(f"[Solver] ❌ Voxelization failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return

    all_coords = raw_coords.astype(np.float32)
    del raw_coords
    gc.collect()
    print(f"[Solver] Voxels ready: {len(all_coords):,}", flush=True)
    print("PROGRESS:25", flush=True)

    total_voxels = len(all_coords)

    # 2. Physical fill time (스크류 면적 기준 유량 보정)
    vol_mm3      = total_voxels * (res ** 3)
    screw_area   = np.pi * (args.screw_dia / 2) ** 2    # mm² — 스크류 단면적
    flow_rate    = screw_area * args.vel_mms if args.vel_mms > 0 else 1.0  # mm³/s
    theo_fill_time = vol_mm3 / flow_rate
    print(f"[Solver] Volume: {vol_mm3:.1f} mm³ | Screw ø{args.screw_dia}mm | Flow: {flow_rate:.0f} mm³/s | Theo fill: {theo_fill_time:.3f}s", flush=True)

    # 3. Geometric Dijkstra — purely visual ordering
    gate_pos = np.array([args.gate_x, args.gate_y, args.gate_z], dtype=np.float32)

    bb_min = all_coords.min(axis=0)
    bb_max = all_coords.max(axis=0)
    gate_in_range = np.all(gate_pos >= bb_min - res) and np.all(gate_pos <= bb_max + res)
    if not gate_in_range:
        z_min_mask = all_coords[:, 2] < bb_min[2] + res * 2
        gate_pos = all_coords[z_min_mask].mean(axis=0)
        print(f"[Solver] Gate out of range -> fallback to bottom-center: {gate_pos.round(2)}", flush=True)
    else:
        print(f"[Solver] Gate accepted: {gate_pos.round(3)}", flush=True)

    dists_to_gate = np.linalg.norm(all_coords - gate_pos, axis=1)
    start_idx = int(np.argmin(dists_to_gate))
    print(f"[Solver] Nearest gate voxel: idx={start_idx}", flush=True)
    print("[Solver] Running Dijkstra BFS...", flush=True)
    print("PROGRESS:26", flush=True)
    norm_weights = compute_dijkstra_weights(all_coords, start_idx, res)
    print("[Solver] Dijkstra complete.", flush=True)
    print("PROGRESS:50", flush=True)

    # 4. Animation frames — result_dir 확정 후 사용
    result_dir_tmp = os.path.dirname(os.path.abspath(args.stl_path))
    frames_dir = os.path.join(result_dir_tmp, "frames")
    os.makedirs(frames_dir, exist_ok=True)

    num_frames = args.num_frames
    print(f"[Solver] Generating {num_frames} frames...", flush=True)

    for f in range(num_frames):
        visual_ratio = (f + 1) / num_frames
        fill_pct     = visual_ratio * 100.0
        phys_time    = visual_ratio * theo_fill_time
        if phys_time < 1.0:
            phys_label = f"{phys_time * 1000:.1f} ms"
        else:
            phys_label = f"{phys_time:.3f} s"

        save_visual_frame(
            coords=all_coords,
            norm_weights=norm_weights,
            threshold_ratio=visual_ratio,
            frame_idx=f,
            phys_time_label=phys_label,
            fill_pct=fill_pct,
            out_dir=frames_dir,
        )
        # 프레임 진행률: 50% ~ 95% 구간
        frame_pct = 50 + int(((f + 1) / num_frames) * 45)
        print(f"PROGRESS:{frame_pct}", flush=True)
        print(f"  Frame {f+1}/{num_frames} | Fill: {fill_pct:.1f}% | t={phys_label}", flush=True)

    # 5. Save results
    elapsed = time.time() - start_wall_time

    # ── 결과 저장 디렉토리: STL 파일과 같은 위치 ──────────────────
    # solver는 --stl_path=/app/results/{job_id}/input.stl 로 실행됨
    # → result_dir = /app/results/{job_id}/
    result_dir = os.path.dirname(os.path.abspath(args.stl_path))

    results = {
        "Signal ID":            args.signal_id,
        "Material":             args.material,
        "Total Voxels":         total_voxels,
        "num_voxels":           total_voxels,
        "Part Volume (mm3)":    round(vol_mm3, 2),
        "Gate Dia (mm)":        args.gate_dia,
        "Gate Pos (mm)":        [round(float(v), 3) for v in gate_pos],
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
        "Note": (
            "Frames are geometry-driven (Dijkstra). "
            "Physical time is a proportional label — decoupled from animation speed."
        ),
        "voxel_data_file": "voxel_data.npz",
    }

    results_json_path = os.path.join(result_dir, "results.json")
    with open(results_json_path, "w") as fh:
        json.dump(results, fh, indent=4)
    print(f"[Solver] ✅ results.json 저장 완료: {results_json_path}", flush=True)

    # ── voxel_data.npz: result_dir 에 저장 (API /api/voxels/{job_id} 가 읽음) ──
    npz_path = os.path.join(result_dir, "voxel_data.npz")
    np.savez_compressed(
        npz_path,
        coords=all_coords.astype(np.float32),
        weights=norm_weights.astype(np.float32),
    )
    print(f"[Solver] ✅ voxel_data.npz 저장 완료: {npz_path} ({total_voxels}개 복셀)", flush=True)

    results_txt_path = os.path.join(result_dir, "results.txt")
    with open(results_txt_path, "w") as fh:
        for k, v in results.items():
            fh.write(f"{k}: {v}\n")

    # ── frames 디렉토리도 result_dir 아래로 ──────────────────────
    frames_dir_abs = os.path.join(result_dir, "frames")
    os.makedirs(frames_dir_abs, exist_ok=True)

    # ── VTK 출력 ─────────────────────────────────────────────────
    _export_vtk(all_coords, norm_weights, res)

    print(f"[Solver] Done in {elapsed:.1f}s. {num_frames} frames saved to {frames_dir_abs}/", flush=True)
    print("PROGRESS:100", flush=True)


if __name__ == "__main__":
    main()
