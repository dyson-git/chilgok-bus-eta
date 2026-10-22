import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_live_config  # noqa: E402
import pytest  # noqa: E402

# live-config.js는 키가 들어 있어 커밋하지 않는다(.gitignore). 없으면 건너뛴다.
pytestmark = pytest.mark.skipif(not (ROOT / "live-config.js").exists(), reason="live-config.js 없음(로컬 생성 전용)")


def _load():
    text = (ROOT / "live-config.js").read_text(encoding="utf-8")
    m = re.fullmatch(r"window\.LIVE_CONFIG = (.*);\s*", text, re.S)
    assert m, "live-config.js format changed"
    return json.loads(m.group(1))


def test_live_config_matches_collector_config():
    cfg = _load()
    assert cfg["directions"] == gen_live_config.build_directions()


def test_live_config_has_nonblank_key():
    key = _load()["serviceKey"]
    assert key and key == key.strip()
