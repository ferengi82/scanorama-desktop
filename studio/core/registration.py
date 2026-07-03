"""Automatische Registrierung mehrerer Standpunkte (Port aus Scanner-v1).

Pipeline (bewährt aus merge_scans.py, inkl. der 2026-04-Fixes):
  1. **Global Registration**: FPFH-Feature-Deskriptoren + RANSAC —
     grobe Ausrichtung ohne Vorwissen (Zentimeter-Genauigkeit)
  2. **Multi-Scale-ICP** (Point-to-Plane, 3 Stufen grob→fein) —
     Feinregistrierung im Millimeterbereich
  3. **Pose-Graph-Optimierung** (bei >2 Standpunkten): Odometrie-Kette
     + Loop-Closure-Kanten, verteilt Restfehler global

Voraussetzung: >30 % Überlappung und geometrische Struktur in der
Szene (Ecken, Möbel — nicht nur glatte Wände).
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field

import numpy as np

from .cloud import PointCloud

log = logging.getLogger(__name__)


@dataclass
class RegistrationParams:
    voxel_global_m: float = 0.10     # Downsampling für FPFH/RANSAC
    icp_threshold_m: float = 0.05    # max. Korrespondenzdistanz ICP
    min_fitness: float = 0.10        # darunter gilt ein Paar als schwach

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PairQuality:
    """Registrierungsgüte eines Standpunkt-Paars (für die Ampel-Anzeige)."""
    source: int
    target: int
    fitness: float                   # Inlier-Anteil 0–1
    rmse_m: float                    # Korrespondenz-RMSE

    @property
    def rating(self) -> str:
        """Ampel: gut / mäßig / schlecht."""
        if self.fitness >= 0.4 and self.rmse_m <= 0.03:
            return "gut"
        if self.fitness >= 0.1:
            return "mäßig"
        return "schlecht"


@dataclass
class RegistrationResult:
    poses: list[np.ndarray]          # 4×4 pro Standpunkt (Index 0 = Referenz)
    pairs: list[PairQuality] = field(default_factory=list)

    def summary(self) -> str:
        lines = []
        for i, T in enumerate(self.poses):
            pos = T[:3, 3]
            yaw = np.degrees(np.arctan2(T[1, 0], T[0, 0]))
            lines.append(f"Standpunkt {i}: ({pos[0]:+.3f}, {pos[1]:+.3f}, "
                         f"{pos[2]:+.3f}) m, Yaw {yaw:+.1f}°")
        for p in self.pairs:
            lines.append(f"Paar {p.source}→{p.target}: Fitness {p.fitness:.3f}, "
                         f"RMSE {p.rmse_m * 1000:.1f} mm — {p.rating}")
        return "\n".join(lines)


def _preprocess(pcd, voxel_size: float):
    """Downsampling + Normalen + FPFH-Features."""
    import open3d as o3d
    down = pcd.voxel_down_sample(voxel_size)
    down.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
        radius=voxel_size * 3, max_nn=30))
    fpfh = o3d.pipelines.registration.compute_fpfh_feature(
        down, o3d.geometry.KDTreeSearchParamHybrid(
            radius=voxel_size * 7, max_nn=100))
    return down, fpfh


def _global_registration(source_down, target_down, source_fpfh, target_fpfh,
                         voxel_size: float):
    import open3d as o3d
    threshold = voxel_size * 2.0
    return o3d.pipelines.registration.registration_ransac_based_on_feature_matching(
        source_down, target_down, source_fpfh, target_fpfh,
        mutual_filter=True,
        max_correspondence_distance=threshold,
        estimation_method=o3d.pipelines.registration.
        TransformationEstimationPointToPoint(False),
        ransac_n=3,
        checkers=[
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnEdgeLength(0.9),
            o3d.pipelines.registration.CorrespondenceCheckerBasedOnDistance(threshold),
        ],
        criteria=o3d.pipelines.registration.RANSACConvergenceCriteria(100000, 0.999),
    )


def pairwise_registration(source: PointCloud, target: PointCloud,
                          params: RegistrationParams) -> tuple[np.ndarray, float, float]:
    """Registriert source auf target: Global → Multi-Scale-ICP.

    Returns:
        (T 4×4, fitness, rmse) — T bildet source-Koordinaten nach target ab
    """
    import open3d as o3d

    src = source.to_open3d()
    tgt = target.to_open3d()

    log.info("  Global Registration (FPFH + RANSAC) …")
    src_down, src_fpfh = _preprocess(src, params.voxel_global_m)
    tgt_down, tgt_fpfh = _preprocess(tgt, params.voxel_global_m)
    result = _global_registration(src_down, tgt_down, src_fpfh, tgt_fpfh,
                                  params.voxel_global_m)
    log.info(f"    Fitness {result.fitness:.4f}, RMSE {result.inlier_rmse:.4f}")
    if result.fitness < 0.05:
        log.warning("    Sehr niedrige Fitness — zu wenig Überlappung?")

    # Multi-Scale-ICP: 3 Stufen grob → fein
    log.info("  ICP-Feinregistrierung (Multi-Scale, Point-to-Plane) …")
    t = params.icp_threshold_m
    scales = [(t * 1.0, t * 2.0), (t * 0.5, t * 1.0), (t * 0.25, t * 0.5)]

    current = result.transformation
    icp = None
    for stage, (voxel, threshold) in enumerate(scales, 1):
        s = src.voxel_down_sample(voxel)
        g = tgt.voxel_down_sample(voxel)
        for pc in (s, g):
            pc.estimate_normals(o3d.geometry.KDTreeSearchParamHybrid(
                radius=voxel * 3, max_nn=30))
        icp = o3d.pipelines.registration.registration_icp(
            s, g, threshold, current,
            o3d.pipelines.registration.TransformationEstimationPointToPlane(),
            o3d.pipelines.registration.ICPConvergenceCriteria(max_iteration=200),
        )
        current = icp.transformation
        log.info(f"    Stufe {stage}/3 (Voxel {voxel * 1000:.0f} mm): "
                 f"Fitness {icp.fitness:.4f}, RMSE {icp.inlier_rmse:.4f}")

    return np.asarray(current), float(icp.fitness), float(icp.inlier_rmse)


def register_stations(clouds: list[PointCloud],
                      params: RegistrationParams | None = None) -> RegistrationResult:
    """Registriert N Standpunkte; Standpunkt 0 ist die Referenz.

    Bei 2 Wolken: eine paarweise Registrierung. Bei >2: Odometrie-Kette
    + Loop-Closures + Pose-Graph-Optimierung.
    """
    import open3d as o3d

    params = params or RegistrationParams()
    n = len(clouds)
    if n == 0:
        raise ValueError("Keine Wolken zu registrieren")
    if n == 1:
        return RegistrationResult(poses=[np.identity(4)])

    if n == 2:
        log.info("Registriere Standpunkt 1 → 0 …")
        T, fitness, rmse = pairwise_registration(clouds[1], clouds[0], params)
        return RegistrationResult(
            poses=[np.identity(4), T],
            pairs=[PairQuality(1, 0, fitness, rmse)],
        )

    # --- Pose-Graph für n > 2 ---
    o3d_clouds = [c.to_open3d() for c in clouds]
    pose_graph = o3d.pipelines.registration.PoseGraph()
    pose_graph.nodes.append(
        o3d.pipelines.registration.PoseGraphNode(np.identity(4)))
    pairs: list[PairQuality] = []
    odometry = np.identity(4)

    def _information(i, j, T):
        return o3d.pipelines.registration.get_information_matrix_from_point_clouds(
            o3d_clouds[i].voxel_down_sample(params.icp_threshold_m),
            o3d_clouds[j].voxel_down_sample(params.icp_threshold_m),
            params.icp_threshold_m, T)

    for i in range(n - 1):
        log.info(f"Registriere Standpunkt {i} → {i + 1} (Odometrie) …")
        T, fitness, rmse = pairwise_registration(clouds[i], clouds[i + 1], params)
        pairs.append(PairQuality(i, i + 1, fitness, rmse))
        odometry = T @ odometry
        pose_graph.nodes.append(
            o3d.pipelines.registration.PoseGraphNode(np.linalg.inv(odometry)))
        info = (_information(i, i + 1, T) if fitness > params.min_fitness
                else np.identity(6) * fitness)
        pose_graph.edges.append(o3d.pipelines.registration.PoseGraphEdge(
            i, i + 1, T, info, uncertain=False))

    for i in range(n):
        for j in range(i + 2, n):
            log.info(f"Registriere Standpunkt {i} ↔ {j} (Loop Closure) …")
            T, fitness, rmse = pairwise_registration(clouds[i], clouds[j], params)
            pairs.append(PairQuality(i, j, fitness, rmse))
            info = (_information(i, j, T) if fitness > params.min_fitness
                    else np.identity(6) * fitness)
            pose_graph.edges.append(o3d.pipelines.registration.PoseGraphEdge(
                i, j, T, info, uncertain=True))

    log.info("Pose-Graph-Optimierung …")
    option = o3d.pipelines.registration.GlobalOptimizationOption(
        max_correspondence_distance=params.icp_threshold_m,
        edge_prune_threshold=0.25,
        reference_node=0,
    )
    o3d.pipelines.registration.global_optimization(
        pose_graph,
        o3d.pipelines.registration.GlobalOptimizationLevenbergMarquardt(),
        o3d.pipelines.registration.GlobalOptimizationConvergenceCriteria(),
        option,
    )

    poses = [np.asarray(pose_graph.nodes[i].pose) for i in range(n)]
    result = RegistrationResult(poses=poses, pairs=pairs)
    log.info("Registrierung fertig:\n" + result.summary())
    return result
