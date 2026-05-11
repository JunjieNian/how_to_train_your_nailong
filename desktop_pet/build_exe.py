#!/usr/bin/env python3
"""
Build the Nailong desktop pet into a standalone Windows .exe application.

Usage:
    python build_exe.py           # build to dist/驯龙高手/
    python build_exe.py --name X  # custom name

Prerequisites:
    pip install pyinstaller
    Run setup_windows.bat first (or prepare_assets.py + download model)
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def check_prereqs() -> bool:
    ok = True

    # Check PyInstaller
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[ERROR] PyInstaller not installed. Run: pip install pyinstaller")
        ok = False

    # Check assets
    if not (HERE / "assets" / "idle").is_dir():
        print("[ERROR] Assets not found. Run: python prepare_assets.py")
        ok = False

    # Check model
    if not (HERE / "face_landmarker.task").exists():
        print("[WARN] face_landmarker.task not found — game will run without camera")

    return ok


def make_ico() -> Path | None:
    """Convert top half of idle/0010.png → icon.ico (shows nailong head)."""
    png = HERE / "assets" / "idle" / "0010.png"
    ico = HERE / "assets" / "icon.ico"
    if ico.exists():
        ico.unlink()  # always rebuild from source frame
    if not png.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(png).convert("RGBA")
        w, h = img.size
        # Crop top half to show the head
        img = img.crop((0, 0, w, h // 2))
        # Pad to square
        cw, ch = img.size
        side = max(cw, ch)
        square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        square.paste(img, ((side - cw) // 2, (side - ch) // 2))
        sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
        square.save(ico, format="ICO", sizes=sizes)
        print(f"[OK] Created {ico.name} (head crop from idle/0010.png)")
        return ico
    except Exception as e:
        print(f"[WARN] Could not create .ico: {e}")
        return None


def build(name: str = "驯龙高手") -> None:
    if not check_prereqs():
        sys.exit(1)

    ico = make_ico()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--name", name,
        # Bundle assets
        "--add-data", f"assets{';' if sys.platform == 'win32' else ':'}assets",
    ]

    # Bundle model if present
    model = HERE / "face_landmarker.task"
    if model.exists():
        sep = ";" if sys.platform == "win32" else ":"
        cmd += ["--add-data", f"face_landmarker.task{sep}."]

    if ico:
        cmd += ["--icon", str(ico)]

    # Hidden imports that PyInstaller might miss
    cmd += [
        "--hidden-import", "PySide6.QtMultimedia",
        "--hidden-import", "config",
        "--hidden-import", "game_engine",
        "--hidden-import", "video_controller",
        "--hidden-import", "smile_detector",
    ]

    # Exclude heavy packages we don't use (avoids Anaconda bloat & conflicts)
    for mod in (
        "matplotlib", "scipy", "pandas", "tensorflow", "torch",
        "IPython", "notebook", "jupyter", "PIL.ImageTk", "tkinter",
        "PyQt5", "PyQt6", "wx", "gtk", "gi",
        "setuptools", "pkg_resources", "pytest",
        "sounddevice", "h5py", "sympy", "docutils", "sphinx",
    ):
        cmd += ["--exclude-module", mod]

    cmd.append("main.py")

    print(f"\n[BUILD] Running PyInstaller...")
    print(f"  Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(HERE))
    if result.returncode != 0:
        print("\n[ERROR] Build failed")
        sys.exit(1)

    dist = HERE / "dist" / name
    print(f"\n{'='*50}")
    print(f"  Build complete!")
    print(f"  Output: {dist}")
    print(f"  Exe:    {dist / (name + '.exe')}")
    print(f"{'='*50}")
    print(f"\nTo run: double-click {name}.exe in {dist}")
    print(f"To distribute: zip the entire '{name}' folder")


def main():
    ap = argparse.ArgumentParser(description="Build Nailong desktop pet .exe")
    ap.add_argument("--name", default="驯龙高手", help="Application name (default: 驯龙高手)")
    args = ap.parse_args()
    build(name=args.name)


if __name__ == "__main__":
    main()
