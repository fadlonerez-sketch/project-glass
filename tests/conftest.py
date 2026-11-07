import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# Pipe names carry a per-run suffix, so tests never reach a Glass that is running on this PC (or vice versa).
SESSION_PIPE_SUFFIX = "test" + uuid.uuid4().hex[:8]


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own Glass data folder and pipe names; nothing touches the real
    %LOCALAPPDATA%\\ProjectGlass or a Glass that is running."""
    data = tmp_path / "glass-data"
    monkeypatch.setenv("GLASS_DATA_DIR", str(data))
    monkeypatch.setenv("GLASS_PIPE_SUFFIX", SESSION_PIPE_SUFFIX)
    monkeypatch.setenv("LAUNCHDECK_DATA_DIR", str(tmp_path / "launchdeck-data"))
    yield data
