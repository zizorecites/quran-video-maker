# How PyInstaller packs the app into a Mac .app or a Windows program.
# Run from the project folder:   pyinstaller build/app.spec
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).parent
NAME = "Quran Video Maker"

datas = [
    (str(ROOT / "engine"), "engine"),
    (str(ROOT / "resources"), "resources"),
    (str(ROOT / "ui"), "ui"),
]
binaries = []
hidden = ["quranvid", "listen", "english_map", "arabic_text", "qvm", "qvm.core",
          "qvm.server", "qvm.native", "qvm.paths"]
# (onnxruntime is left out on purpose: faster-whisper only uses it for a
#  silence filter the app switches off - it saves about 60 MB)
for pkg in ("faster_whisper", "ctranslate2", "imageio_ffmpeg", "uharfbuzz", "freetype",
            "av", "tokenizers", "certifi", "webview", "huggingface_hub"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hidden += h
if sys.platform == "win32":          # the Windows window uses Edge through .NET
    for pkg in ("pythonnet", "clr_loader"):
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hidden += h
    hidden += ["clr"]

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT), str(ROOT / "engine")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["onnxruntime", "hf_xet", "tkinter", "matplotlib", "IPython", "pytest", "PyQt5", "PyQt6", "PySide2",
              "PySide6", "torch", "tensorflow"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name=NAME,
    console=False,
    icon=str(ROOT / "build" / ("icon.icns" if sys.platform == "darwin" else "icon.ico")),
    target_arch=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name=NAME)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name=NAME + ".app",
        icon=str(ROOT / "build" / "icon.icns"),
        bundle_identifier="com.zizorecites.quranvideomaker",
        info_plist={
            "CFBundleDisplayName": NAME,
            "CFBundleShortVersionString": "1.0.0",
            "CFBundleVersion": "1.0.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "NSHumanReadableCopyright": "by @zizorecites",
        },
    )
