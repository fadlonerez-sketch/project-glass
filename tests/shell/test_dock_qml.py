"""The real Dock QML, measured off-screen (tools/preview/dockprobe.py): stable geometry under magnification, preview and
tooltip placement within the display, input regions, departure animation, several display sizes and DPI scales.
No input is injected and nothing appears on any monitor."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RUNNING = {"app:Google Chrome", "app:File Explorer", "app:WhatsApp", "app:Terminal"}


def probe(tmp_path, *extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("QT_")}
    env["GLASS_DATA_DIR"] = str(tmp_path / "data")
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "preview" / "dockprobe.py"), *extra], capture_output=True,
                       text=True, timeout=240, env=env, cwd=str(ROOT))
    assert r.returncode == 0, r.stderr[-3000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


CONFIGS = {
    "1080p": ["--width", "1920", "--height", "1080"],
    "1440p": ["--width", "2560", "--height", "1440"],
    "laptop-150%": ["--width", "1707", "--height", "1067", "--scale", "1.5"],
    "small": ["--width", "1280", "--height", "720"],
}


@pytest.fixture(scope="module", params=list(CONFIGS))
def measured(request, tmp_path_factory):
    return request.param, probe(tmp_path_factory.mktemp(request.param), *CONFIGS[request.param])


def test_no_qml_warnings(measured):
    _, d = measured
    assert d["warnings"] == []


def test_bar_is_thin_and_spans_the_display(measured):
    name, d = measured
    bar, win = d["bar"], d["window"]
    assert bar["barW"] == pytest.approx(win["w"] - 20)               # full width, 10 px margins
    assert bar["barH"] <= 56 and bar["reservedThickness"] <= 64      # much thinner than the old 78 px Dock
    assert bar["barY"] + bar["barH"] + 6 == pytest.approx(win["h"])  # sits 6 px above the screen edge
    if name == "laptop-150%":
        assert win["dpr"] == pytest.approx(1.5)


def test_magnification_never_moves_any_slot(measured):
    _, d = measured
    rest = d["rest"]
    for hovered, slots in d["magnified"].items():
        for uid, s in slots.items():
            assert (s["x"], s["y"], s["w"], s["h"]) == (rest[uid]["x"], rest[uid]["y"], rest[uid]["w"], rest[uid]["h"]), (hovered, uid)
        assert slots[hovered]["mag"] == pytest.approx(1.3, abs=0.01)    # the icon under the pointer is fully magnified
        far = [u for u in slots if slots[u]["kind"] == "widget"]
        assert all(slots[u]["mag"] == 1 for u in far)                    # widgets never magnify


def test_apps_share_one_consistent_spacing(measured):
    _, d = measured
    apps = sorted((s for s in d["rest"].values() if s["kind"] == "app" and s["w"] > 0), key=lambda s: s["x"])
    steps = {round(b["x"] - a["x"], 2) for a, b in zip(apps, apps[1:])}
    assert len(steps) <= 2          # one step between icons, a wider one across the Open | Recent separator


def test_previews_for_open_apps_tooltips_for_closed_ones(measured):
    _, d = measured
    win, bar = d["window"], d["bar"]
    for uid, p in d["placements"].items():
        if uid in RUNNING:
            assert p["state"] == "preview" and p["shown_preview"] == uid and p["preview_visible"]
            x, y, w, h = p["preview"]
            m = p["margin"]
            assert x + m >= 0 and x + w - m <= win["w"], uid          # stays on the display
            assert y + h - m < bar["barY"], uid                       # above the Dock, never covering it
            r = p["region"]
            assert r["y"] <= y + m and r["h"] >= h - 2 * m            # the open preview takes input
        else:
            assert p["state"] == "tooltip" and p["shown_tip"] == uid and not p["preview_visible"]
            assert p["tooltip"] == uid.split(":", 1)[1]


def test_input_region_is_only_the_bar_at_rest(measured):
    _, d = measured
    bar = d["bar"]
    for key in ("region_rest", "region_after"):
        r = d[key]
        assert r["h"] <= bar["barH"] + 12 and r["y"] >= bar["barY"] - 6, key   # nothing above the bar blocks clicks


def test_closing_app_collapses_and_neighbours_close_the_gap(measured):
    _, d = measured
    s = d["leaving"]
    assert s["app:WhatsApp"]["w"] == 0
    step = d["rest"]["app:File Explorer"]["x"] - d["rest"]["app:Google Chrome"]["x"]
    assert s["app:Terminal"]["x"] - s["app:File Explorer"]["x"] == pytest.approx(step)
