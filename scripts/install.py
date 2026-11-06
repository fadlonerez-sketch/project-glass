"""Install Project Glass for the current user (no administrator rights needed).

    py -3 scripts\\install.py              install / repair
    py -3 scripts\\install.py --startup    also start Glass when you sign in
    py -3 scripts\\install.py --uninstall  remove shortcuts and the startup entry (your data is kept)

Steps: checks Python/PySide6, creates .venv (with system site-packages), installs requirements, registers the
package path (.pth), compiles the Liquid Glass shader, writes the app icon, and creates Start-menu
shortcuts with proper AppUserModelIDs: "Project Glass", "Glass Control Center" and "Restore Windows Desktop".
Nothing system-wide is changed. Uses only signed binaries (Python, Qt), so Smart App Control stays on.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV = ROOT / ".venv"
START_MENU = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Project Glass"
SHORTCUTS = [
    ("Project Glass", "glass.shell", [], "ProjectGlass.Shell", "Start the Project Glass desktop"),
    ("Glass Control Center", "glass.controlcenter", [], "ProjectGlass.ControlCenter", "Personalise Project Glass"),
    ("Restore Windows Desktop", "glass.recovery", ["--restore"], "ProjectGlass.Recovery",
     "Quit Project Glass and bring back the standard Windows taskbar"),
]


def step(msg: str) -> None:
    print(f"  • {msg}", flush=True)


def venv_python(windowed: bool = False) -> Path:
    return VENV / "Scripts" / ("pythonw.exe" if windowed else "python.exe")


def ensure_venv() -> None:
    if not venv_python().exists():
        step("creating .venv (with system site-packages)")
        venv.EnvBuilder(system_site_packages=True, with_pip=True).create(VENV)
    step("installing requirements")
    subprocess.check_call([str(venv_python()), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                           "-r", str(ROOT / "requirements.txt")])
    site = subprocess.check_output([str(venv_python()), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
                                   text=True).strip()
    pth = Path(site) / "projectglass.pth"
    pth.write_text(str(ROOT) + "\n", encoding="utf-8")
    step(f"registered the glass package ({pth.name})")


def compile_shader() -> None:
    src = ROOT / "glass" / "ui" / "shaders" / "liquidglass.frag"
    out = src.with_suffix(".frag.qsb")
    qsb = subprocess.check_output([str(venv_python()), "-c", "import PySide6, os; print(os.path.join(os.path.dirname(PySide6.__file__), 'qsb.exe'))"],
                                  text=True).strip()
    if not Path(qsb).exists():
        if out.exists():
            step("qsb.exe not found; using the precompiled shader")
            return
        raise SystemExit("PySide6's qsb.exe is missing and no compiled shader exists.")
    if not out.exists() or out.stat().st_mtime < src.stat().st_mtime:
        subprocess.check_call([qsb, "--glsl", "100 es,120,150", "--hlsl", "50", "--msl", "12", "-o", str(out), str(src)])
    step("Liquid Glass shader ready")


def write_icon() -> Path:
    ico = ROOT / "assets" / "glass.ico"
    code = (
        "import sys\n"
        "from PySide6.QtGui import QGuiApplication, QImage, QPainter, QColor, QRadialGradient, QLinearGradient\n"
        "from PySide6.QtCore import Qt, QRectF\n"
        "app = QGuiApplication(sys.argv)\n"
        "img = QImage(256, 256, QImage.Format.Format_ARGB32); img.fill(Qt.GlobalColor.transparent)\n"
        "p = QPainter(img); p.setRenderHint(QPainter.RenderHint.Antialiasing)\n"
        "g = QLinearGradient(0, 0, 256, 256); g.setColorAt(0, QColor('#B596FF')); g.setColorAt(1, QColor('#6E3BF0'))\n"
        "p.setBrush(g); p.setPen(Qt.PenStyle.NoPen); p.drawRoundedRect(QRectF(8, 8, 240, 240), 58, 58)\n"
        "r = QRadialGradient(96, 80, 120); r.setColorAt(0, QColor(255, 255, 255, 150)); r.setColorAt(1, QColor(255, 255, 255, 0))\n"
        "p.setBrush(r); p.drawEllipse(QRectF(40, 40, 176, 176))\n"
        "p.setBrush(Qt.BrushStyle.NoBrush); pen = p.pen(); p.setPen(QColor(255, 255, 255, 235))\n"
        "from PySide6.QtGui import QPen\n"
        "p.setPen(QPen(QColor(255, 255, 255, 235), 14)); p.drawEllipse(QRectF(64, 64, 128, 128))\n"
        "p.end(); img.save(sys.argv[1], 'ICO')\n"
    )
    ico.parent.mkdir(exist_ok=True)
    subprocess.check_call([str(venv_python()), "-c", code, str(ico)], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    step("app icon written")
    return ico


def create_shortcuts(icon: Path) -> None:
    code = r'''
import sys, json
import comtypes, comtypes.client
from comtypes.shelllink import ShellLink, IShellLinkW
from comtypes.persist import IPersistFile
from ctypes import byref, c_void_p, wintypes, cast, POINTER, c_wchar_p
from glass.win.shellcom import IPropertyStore, PROPERTYKEY, PROPVARIANT, PKEY_AppUserModel_ID, ole32
items = json.loads(sys.argv[1])
for it in items:
    link = comtypes.client.CreateObject(ShellLink, interface=IShellLinkW)
    link.SetPath(it["target"]); link.SetArguments(it["args"]); link.SetWorkingDirectory(it["cwd"])
    link.SetDescription(it["desc"]); link.SetIconLocation(it["icon"], 0)
    store = link.QueryInterface(IPropertyStore)
    pv = PROPVARIANT(); pv.vt = 31
    s = c_wchar_p(it["aumid"]); pv.p = cast(s, c_void_p)
    store.SetValue(byref(PKEY_AppUserModel_ID), byref(pv)); store.Commit()
    link.QueryInterface(IPersistFile).Save(it["path"], True)
'''
    import json
    START_MENU.mkdir(parents=True, exist_ok=True)
    items = []
    for name, module, args, aumid, desc in SHORTCUTS:
        items.append({"path": str(START_MENU / f"{name}.lnk"), "target": str(venv_python(windowed=True)),
                      "args": " ".join(["-m", module] + args), "cwd": str(ROOT), "icon": str(icon), "aumid": aumid, "desc": desc})
    subprocess.check_call([str(venv_python()), "-c", code, json.dumps(items)], cwd=str(ROOT))
    step(f"Start-menu shortcuts in {START_MENU}")


def set_startup(enabled: bool) -> None:
    subprocess.check_call([str(venv_python()), "-c",
                           f"from glass.win import startup; startup.set_enabled({enabled})"], cwd=str(ROOT))
    step("start with Windows: " + ("on" if enabled else "off"))


def uninstall() -> None:
    print("Removing Project Glass shortcuts and startup entry (your settings and data are kept)…")
    if venv_python().exists():
        subprocess.call([str(venv_python()), "-m", "glass.recovery", "--restore"], cwd=str(ROOT))
        set_startup(False)
    for name, *_ in SHORTCUTS:
        (START_MENU / f"{name}.lnk").unlink(missing_ok=True)
    try:
        START_MENU.rmdir()
    except OSError:
        pass
    print("Done. Data folder: %LOCALAPPDATA%\\ProjectGlass (delete it to remove everything).")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--startup", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    args = ap.parse_args()
    if sys.platform != "win32" or sys.version_info < (3, 11):
        raise SystemExit("Project Glass needs Windows and Python 3.11 or newer.")
    if args.uninstall:
        uninstall()
        return 0
    print("Installing Project Glass…")
    ensure_venv()
    compile_shader()
    icon = write_icon()
    create_shortcuts(icon)
    if args.startup:
        set_startup(True)
    print("\nInstalled. Start it from Start › Project Glass, or run:\n"
          f'  "{venv_python(windowed=True)}" -m glass.shell\n'
          "Recovery at any time: Ctrl+Alt+Shift+R, or Start › Project Glass › Restore Windows Desktop.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
