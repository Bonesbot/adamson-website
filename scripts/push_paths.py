#!/usr/bin/env python3
"""
Push a set of working-tree paths to GitHub as ONE commit on top of the remote branch head,
via the Git Data API (blobs -> tree -> commit -> ref). No local git operations, so it works
when .git/index.lock is stale or local main is behind origin (the daily job commits through
the Contents API, so it usually is). One commit means one Netlify build.

    python scripts/push_paths.py -m "message" path [path ...]      (directories are walked)
    python scripts/push_paths.py --dry-run -m "x" path ...           (list what would go)

Inputs from .env: GITHUB_TOKEN (Contents:write), GITHUB_REPO (default Bonesbot/adamson-website),
GITHUB_BRANCH (default main). Unchanged files (same blob as on the remote) are skipped.
"""
import argparse, base64, json, os, sys, hashlib, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_env():
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

def api(method, url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "User-Agent": "adamsonfl-push-paths", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.loads(r.read() or b"{}")

def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("-m", required=True); ap.add_argument("--dry-run", action="store_true"); ap.add_argument("paths", nargs="+")
    a = ap.parse_args(); load_env()
    token = os.environ.get("GITHUB_TOKEN"); repo = os.environ.get("GITHUB_REPO", "Bonesbot/adamson-website"); branch = os.environ.get("GITHUB_BRANCH", "main")
    if not token: sys.exit("GITHUB_TOKEN missing")
    files = []
    for p in a.paths:
        full = os.path.join(ROOT, p)
        if os.path.isdir(full):
            for d, _, fs in os.walk(full):
                for f in fs: files.append(os.path.relpath(os.path.join(d, f), ROOT).replace(os.sep, "/"))
        elif os.path.isfile(full): files.append(p.replace(os.sep, "/"))
        else: sys.exit(f"not found: {p}")
    base = f"https://api.github.com/repos/{repo}"
    head = api("GET", f"{base}/git/ref/heads/{branch}", token)["object"]["sha"]
    base_tree = api("GET", f"{base}/git/commits/{head}", token)["tree"]["sha"]
    # remote blob shas, to skip unchanged files
    remote = {}
    for t in api("GET", f"{base}/git/trees/{base_tree}?recursive=1", token).get("tree", []):
        if t["type"] == "blob": remote[t["path"]] = t["sha"]
    entries, skipped = [], []
    for f in sorted(set(files)):
        data = open(os.path.join(ROOT, f), "rb").read()
        if remote.get(f) == git_blob_sha(data): skipped.append(f); continue
        entries.append((f, data))
    print(f"remote {branch} @ {head[:8]}; {len(entries)} changed, {len(skipped)} unchanged")
    for f, _ in entries: print("  +", f)
    if a.dry_run or not entries: return
    tree = []
    for f, data in entries:
        sha = api("POST", f"{base}/git/blobs", token, {"content": base64.b64encode(data).decode(), "encoding": "base64"})["sha"]
        tree.append({"path": f, "mode": "100644", "type": "blob", "sha": sha})
    new_tree = api("POST", f"{base}/git/trees", token, {"base_tree": base_tree, "tree": tree})["sha"]
    commit = api("POST", f"{base}/git/commits", token, {"message": a.m, "tree": new_tree, "parents": [head]})["sha"]
    api("PATCH", f"{base}/git/refs/heads/{branch}", token, {"sha": commit, "force": False})
    print(f"pushed {commit[:8]} -> {branch}: https://github.com/{repo}/commit/{commit}")

if __name__ == "__main__": main()
