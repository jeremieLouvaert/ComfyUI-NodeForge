"""
Build / refresh the local pack index for the NodeForge retrieval stage.

Sources (schemas confirmed live 2026-05-30, see docs/retrieval-model.md):
  - ComfyUI-Manager custom-node-list.json (one GitHub-raw fetch; the complete
    community pack list with title + description + reference repo URL).
  - registry.comfy.org /nodes (paginated; adds health: github_stars, downloads,
    latest_version.deprecated, status, publisher.status). Optional enrichment.

Freshness policy (sub-question i): cache to JSON with a fetched_at timestamp,
refresh on use if older than TTL_HOURS; on fetch failure fall back to the last
cache and WARN with the cache age (never use a stale index silently).
"""
import os
import json
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "index_cache")
MANAGER_URL = "https://raw.githubusercontent.com/ltdrdata/ComfyUI-Manager/main/custom-node-list.json"
REGISTRY_URL = "https://api.comfy.org/nodes"
TTL_HOURS = 24


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": "NodeForge-retrieval-eval/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _cache_path(name):
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, name)


def _age_hours(path):
    if not os.path.exists(path):
        return None
    try:
        rec = json.load(open(path, encoding="utf-8"))
        return (time.time() - rec.get("fetched_at", 0)) / 3600.0
    except Exception:
        return None


def load_manager_index(force=False, now=None):
    """Return the list of pack dicts from the Manager custom-node-list.json.
    Each pack: {id?, author, title, reference, description, files, install_type}.
    Uses a 24h TTL cache; falls back (with a loud warning) to a stale cache on
    network failure. `now` is injectable for deterministic tests."""
    now = time.time() if now is None else now
    path = _cache_path("manager.json")
    age = _age_hours(path)
    fresh = age is not None and age < TTL_HOURS
    if fresh and not force:
        rec = json.load(open(path, encoding="utf-8"))
        return rec["custom_nodes"]
    try:
        data = _get(MANAGER_URL)
        packs = data["custom_nodes"]
        json.dump({"fetched_at": now, "custom_nodes": packs},
                  open(path, "w", encoding="utf-8"))
        print(f"[index] manager: fetched {len(packs)} packs")
        return packs
    except Exception as e:
        if os.path.exists(path):
            rec = json.load(open(path, encoding="utf-8"))
            print(f"!! [index] manager fetch FAILED ({type(e).__name__}: {e}); "
                  f"using STALE cache aged {age:.1f}h ({len(rec['custom_nodes'])} packs)")
            return rec["custom_nodes"]
        raise RuntimeError(f"manager index unavailable and no cache: {e}")


def registry_health(query, limit=10, timeout=30):
    """Best-effort registry lookup for HEALTH signals on shortlisted packs only
    (bounded HTTP). Returns a dict id->health, or {} on failure. NOTE: the
    registry `search=` param's server-side filtering is unconfirmed (see
    retrieval-model.md), so this is enrichment, not the primary recall path."""
    try:
        url = f"{REGISTRY_URL}?search={urllib.request.quote(query)}&limit={limit}"
        data = _get(url, timeout=timeout)
    except Exception as e:
        print(f"   [index] registry health lookup failed ({type(e).__name__}); skipping")
        return {}
    out = {}
    for n in data.get("nodes", []):
        out[n.get("id", "")] = {
            "github_stars": n.get("github_stars", 0),
            "downloads": n.get("downloads", 0),
            "status": n.get("status", ""),
            "deprecated": (n.get("latest_version") or {}).get("deprecated", False),
            "publisher_status": (n.get("publisher") or {}).get("status", ""),
            "repository": n.get("repository", ""),
        }
    return out


if __name__ == "__main__":
    packs = load_manager_index(force=True)
    # quick shape sanity
    sample = packs[0]
    print("[index] sample keys:", sorted(sample.keys()))
    print("[index] total packs:", len(packs))
