import json
import sqlite3

import pytest

from glass.core import colors, material, theme
from glass.core.settings import SPECS, SettingsError, SettingsStore, defaults


@pytest.fixture
def store(tmp_path):
    return SettingsStore(tmp_path / "settings.db")


def test_initial_liquid_glass_values(store):
    """The chosen default: Crystal Glass at 100% overall intensity, purple accent tinting the glass."""
    assert store.get("glass.intensity") == 1.0
    assert store.get("glass.blur") == 1.0
    assert store.get("glass.refraction") == 1.0
    assert store.get("glass.shine") == 1.0
    assert store.get("appearance.accent") == "#8E5CF7"
    assert store.get("appearance.theme") == "adaptive"
    assert store.get("glass.accent_tint") is True and 0 < store.get("glass.tint_strength") <= 1
    assert material.matching_preset(store.all()) == "crystal"


@pytest.mark.parametrize("key", ["glass.intensity", "glass.blur", "glass.refraction", "glass.shine",
                                 "glass.frost", "glass.edge", "glass.depth", "glass.tint_strength"])
def test_glass_sliders_are_independent(store, key):
    store.patch({"glass.intensity": 0.4, "glass.blur": 0.3, "glass.refraction": 0.7, "glass.shine": 0.2,
                 "glass.frost": 0.9, "glass.edge": 0.1, "glass.depth": 0.5, "glass.tint_strength": 0.25})
    before = store.section("glass")
    res = store.patch({key: 0.85})
    after = store.section("glass")
    assert res.changed == {key: 0.85}
    for k in before:
        if k != key:
            assert after[k] == before[k], f"{k} changed when only {key} was set"


def test_master_zero_keeps_effect_values(store):
    store.patch({"glass.blur": 0.42, "glass.refraction": 0.13, "glass.shine": 0.77})
    store.patch({"glass.intensity": 0.0})
    assert (store.get("glass.blur"), store.get("glass.refraction"), store.get("glass.shine")) == (0.42, 0.13, 0.77)
    eff = material.effective(store.all())
    assert eff == {"blur": 0.0, "refraction": 0.0, "shine": 0.0, "tint": 0.0, "translucency": 0.0}
    store.patch({"glass.intensity": 0.5})
    eff = material.effective(store.all())
    assert eff["blur"] == pytest.approx(0.21) and eff["shine"] == pytest.approx(0.385)


def test_patch_validates_each_key_alone(store):
    res = store.patch({"glass.blur": 2.5, "glass.shine": 0.5, "appearance.accent": "nope", "dock.icon_size": 64,
                       "bogus.key": 1})
    assert set(res.errors) == {"glass.blur", "appearance.accent", "bogus.key"}
    assert res.changed == {"glass.shine": 0.5, "dock.icon_size": 64}
    assert store.get("glass.blur") == 1.0


def test_persistence_and_reset(tmp_path):
    s = SettingsStore(tmp_path / "s.db")
    s.patch({"appearance.accent": "#2f7cf6", "dock.position": "left", "appearance.saved_colors": ["#fff", "#123456", "#FFFFFF"]})
    s2 = SettingsStore(tmp_path / "s.db")
    assert s2.get("appearance.accent") == "#2F7CF6"
    assert s2.get("dock.position") == "left"
    assert s2.get("appearance.saved_colors") == ["#FFFFFF", "#123456"]
    s2.reset(section="appearance")
    assert s2.get("appearance.accent") == colors.DEFAULT_ACCENT
    assert s2.get("dock.position") == "left"


def test_invalid_stored_value_falls_back(tmp_path):
    path = tmp_path / "s.db"
    SettingsStore(path).patch({"dock.icon_size": 60})
    with sqlite3.connect(path) as c:
        c.execute("UPDATE settings SET value = ? WHERE key = 'dock.icon_size'", (json.dumps(9999),))
    s = SettingsStore(path)
    assert s.get("dock.icon_size") == SPECS["dock.icon_size"].default
    assert "dock.icon_size" in s.reset_keys


def test_corrupt_database_is_quarantined(tmp_path):
    path = tmp_path / "s.db"
    path.write_bytes(b"this is not sqlite" * 100)
    s = SettingsStore(path)
    assert s.db.quarantined is not None and s.db.quarantined.exists()
    assert s.get("glass.intensity") == SPECS["glass.intensity"].default


def test_listeners_receive_only_changes(store):
    seen = []
    store.subscribe(seen.append)
    store.patch({"glass.intensity": 0.3})
    store.patch({"glass.intensity": 0.3})  # no-op
    assert seen == [{"glass.intensity": 0.3}]


def test_widget_validation(store):
    with pytest.raises(SettingsError):
        SPECS["dock.widgets"].coerce("dock.widgets", [{"type": "nonsense"}])
    res = store.patch({"dock.widgets": [{"id": "w1", "type": "weather"}, {"id": "c1", "type": "calendar"}]})
    assert [w["type"] for w in store.get("dock.widgets")] == ["weather", "calendar"]
    assert res.changed
    with pytest.raises(SettingsError):
        SPECS["dock.widgets"].coerce("dock.widgets", [{"type": "weather"}] * 7)


def test_every_default_is_valid():
    for key, value in defaults().items():
        SPECS[key].coerce(key, value)


def test_colors_roundtrip_and_contrast():
    assert colors.parse_hex("abc") == "#AABBCC"
    assert colors.from_rgb(*colors.to_rgb("#8E5CF7")) == "#8E5CF7"
    h, s, l = colors.to_hsl("#8E5CF7")
    assert colors.from_hsl(h, s, l) == "#8E5CF7"
    assert colors.from_hsv(*colors.to_hsv("#2F7CF6")) == "#2F7CF6"
    assert colors.contrast("#FFFFFF", "#000000") == pytest.approx(21.0)
    with pytest.raises(colors.ColorError):
        colors.parse_hex("#12345")
    with pytest.raises(colors.ColorError):
        colors.from_rgb(256, 0, 0)


@pytest.mark.parametrize("accent", [p[1] for p in colors.PRESETS] + ["#000000", "#FFFFFF", "#FFFF00"])
@pytest.mark.parametrize("dark", [False, True])
def test_accent_tones_stay_legible(accent, dark):
    t = colors.accent_tones(accent, dark)
    assert colors.contrast(t["on_accent"], t["accent"]) >= 3.0
    surface = "#1D1D22" if dark else "#FFFFFF"
    assert colors.contrast(t["accent_text"], surface) >= 3.0


def test_theme_modes():
    assert theme.resolve_mode("adaptive", True) == "dark"
    assert theme.resolve_mode("adaptive", False) == "light"
    assert theme.resolve_mode("light", True) == "light"
    light = theme.tokens(defaults(), system_dark=False)
    dark = theme.tokens(defaults(), system_dark=True)
    assert light["mode"] == "light" and dark["mode"] == "dark"
    assert light["text"] != dark["text"]
    for tok in (light, dark):
        assert colors.contrast(tok["text"], tok["surface"]) >= 12
        assert colors.contrast(tok["text2"], tok["surface"]) >= 4.5


def test_theme_file(tmp_path):
    tok = theme.tokens({**defaults(), "appearance.accent": "#E5484D"}, system_dark=False)
    path = tmp_path / "theme.json"
    theme.write_theme_file(path, tok)
    data = json.loads(path.read_text())
    assert data["version"] == 1 and data["mode"] == "light" and data["accent"].startswith("#")


def test_material_uniforms_monotonic():
    assert material.tint_opacity(1.0, 0.0) < material.tint_opacity(0.0, 0.0)
    assert material.tint_opacity(0.6, 1.0) > material.tint_opacity(0.6, 0.0)
    u = material.uniforms(defaults(), theme.tokens(defaults(), False))
    assert u["intensity"] == 1.0 and u["blur"] == 1.0 and 0 < u["tintOpacity"] < 1
    tok = theme.tokens(defaults(), False)
    assert u["preset"] == "crystal" and u["tintStrength"] > 0 and u["accentColor"] == tok["accent"]


def test_presets_are_complete_and_distinct():
    keys = set(next(iter(material.PRESETS.values())))
    for name, preset in material.PRESETS.items():
        assert set(preset) == keys, name
        for k, v in preset.items():
            assert SPECS[k].coerce(k, v) == v
        assert material.matching_preset({**defaults(), **preset}) == name
    vals = [tuple(p.values()) for p in material.PRESETS.values()]
    assert len(set(vals)) == len(vals)


def test_choosing_a_preset_then_adjusting_is_custom(store):
    store.patch(dict(material.PRESETS["subtle"]))
    assert material.matching_preset(store.all()) == "subtle"
    store.patch({"glass.blur": 0.5})
    assert material.matching_preset(store.all()) == "custom"
    assert store.get("glass.refraction") == material.PRESETS["subtle"]["glass.refraction"]   # others untouched


def test_accent_tint_switch_zeroes_tint_but_keeps_strength(store):
    store.patch({"glass.tint_strength": 0.6, "glass.accent_tint": False})
    u = material.uniforms(store.all(), theme.tokens(store.all(), True))
    assert u["tintStrength"] == 0.0 and store.get("glass.tint_strength") == 0.6
    store.patch({"glass.accent_tint": True})
    assert material.uniforms(store.all(), theme.tokens(store.all(), True))["tintStrength"] == 0.6


def test_symbol_lists_validate():
    spec = SPECS["markets.watchlist"]
    assert spec.coerce("markets.watchlist", ["aapl", " msft ", "AAPL", "^gspc", "brk.b"]) == ["AAPL", "MSFT", "^GSPC", "BRK.B"]
    for bad in (["AA PL"], ["<script>"], "AAPL", ["X" * 16]):
        with pytest.raises(SettingsError):
            spec.coerce("markets.watchlist", bad)
    with pytest.raises(SettingsError):
        spec.coerce("markets.watchlist", [f"S{i}" for i in range(13)])
