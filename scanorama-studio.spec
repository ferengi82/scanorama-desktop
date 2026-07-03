# PyInstaller-Spezifikation für die Windows-EXE (onedir).
# Bauen:  pyinstaller scanorama-studio.spec --noconfirm
#
# open3d/laspy/pye57 bringen native DLLs und Datendateien mit —
# collect_all sammelt sie vollständig ein.

from PyInstaller.utils.hooks import collect_all

datas = [("studio/ui/translations/*.qm", "studio/ui/translations")]
binaries = []
hiddenimports = []
for pkg in ("open3d", "laspy", "pye57", "lazrs"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["scripts/run_studio.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ScanoramaStudio",
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="ScanoramaStudio",
)
