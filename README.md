# Scanorama Studio

*English — deutsche Version: [README.de.md](README.de.md)*

Desktop application (Windows-first, Python + Qt) that processes the raw
data recorded by the [scanorama](https://github.com/ferengi82/scanorama)
3D LiDAR scanner: import scan folders (from disk or via SSH from the
Raspberry Pi), compute and filter point clouds, register and fuse
multiple stations, inspect and measure in a built-in 3D viewer, and
export to E57 / PLY / LAS.

**Status:** planning complete, implementation starting — see
[docs/dev/PLAN.md](docs/dev/PLAN.md) (milestones M1–M7) and
[docs/dev/STATUS.md](docs/dev/STATUS.md).

## Planned v1 features

- Raw scan folder → filtered, floor-aligned point cloud (tripod region,
  close range, statistical outliers; elevation offset calibration)
- Project concept: one project = one survey with multiple stations
- Automatic registration (FPFH + RANSAC → multi-scale ICP → pose graph)
  and distance-weighted fusion
- OpenGL point cloud viewer: coloring, distance measuring, clipping,
  point info
- Scan transfer from the Pi over SSH
- Exports: E57, PLY, LAS/LAZ
- UI in German and English; ships as pip package and Windows EXE

## License

MIT — see [LICENSE](LICENSE).
