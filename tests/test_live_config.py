import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import gen_live_config  # noqa: E402
from collector import config  # noqa: E402


def _load():
    text = (ROOT / "live-config.js").read_text(encoding="utf-8")
    m = re.fullmatch(r"window\.LIVE_CONFIG = (.*);\s*", text, re.S)
    assert m, "live-config.js format changed"
    return json.loads(m.group(1))


def test_live_config_matches_collector_config():
    cfg = _load()
    assert cfg["directions"] == gen_live_config.build_directions()


def test_live_config_has_no_key():
    text = (ROOT / "live-config.js").read_text(encoding="utf-8")
    assert "serviceKey" not in text
    assert not re.search(r"[A-Za-z0-9+/=%]{80,}", text)
    assert _load()["relayUrl"].startswith("https://")


def test_worker_allowlist_matches_collector_config():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    block = re.search(r"ALLOWED_NODES\s*=\s*new Set\(\[(.*?)\]\)", js, re.S).group(1)
    nodes = set(re.findall(r'"([^"]+:[^"]+)"', block))
    expected = {f"{r['city_code']}:{r['node_id']}"
                for d in config.DIRECTIONS.values() for r in d["registrations"]}
    assert nodes == expected


def test_worker_has_all_route():
    js = (ROOT / "worker" / "relay.js").read_text(encoding="utf-8")
    assert '"/all"' in js and "Promise.allSettled" in js
