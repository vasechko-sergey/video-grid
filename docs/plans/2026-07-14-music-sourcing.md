# Music Sourcing (B3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Source candidate tracks from the internet when the brief has a mood but no track and no local folder — rank them by fit to `SPEC.mood` (reusing the mood engine) into a `MUSIC_SHORTLIST`, then fetch the pick to a cache — closing montage §5.5's "track sourced (per `music.mode`)" gate for the `free` and `any` rights lanes.

**Architecture:** Two network boundaries + two thin drivers, mirroring the mood-match slice. `scripts/lib/catalog.py` (the discovery boundary: `Candidate` wire-contract + per-source search over stdlib `urllib` / a `yt-dlp` module subprocess + `preview_clip`) and `scripts/lib/fetch.py` (the download boundary: `FetchedTrack` + cache + sidecar + responsibility log) isolate all network; `scripts/music_find.py` reuses `beats.mood_features` + the pure `scripts/lib/mood` core to rank previews → `MUSIC_SHORTLIST.{json,md}`; `scripts/music_fetch.py` downloads the picked row. `free` = ccMixter (no key) with a Jamendo upgrade when `JAMENDO_CLIENT_ID` is configured; `any` = YouTube via yt-dlp (default) + iTunes/Deezer opt-in, behind an explicit responsibility switch.

**Tech Stack:** Python 3 (stdlib `urllib`/`subprocess`), `yt-dlp` (opt-in, invoked as a module — mirrors the demucs boundary), librosa (via the existing `beats.mood_features`), pytest (`pythonpath = .`, marker `integration`). No `requests` dependency.

**Spec:** `docs/specs/2026-07-14-music-sourcing-design.md`.

---

## Shared conventions (read once)

- **Branch off `main` first** (`git checkout -b feat/music-sourcing`); never commit to `main`, never push (the user pushes `main` himself). Post-review fixes are **separate follow-up commits**, never `git commit --amend`.
- **Scripts run as modules:** `.venv/bin/python -m scripts.music_find ...`; tests import `from scripts.lib import catalog, fetch`, `from scripts import music_find as find`.
- **Run tests without piping through `tail`** (it hides the exit code). Use `; echo "EXIT: $?"` or zsh `$pipestatus[1]`.
- **Fail loud with a remedy** (`ValueError` naming the bad value + the fix); imports at top; every `def` typed; a config-spec validates in `__post_init__`.
- **Commit** per task; end each commit body with `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`. Message convention: `<type>: <summary> (5.5 sourcing)`.
- **No machine mutation.** This slice edits `setup.sh` (Task 10) but **must not run it**, and must not `pip install yt-dlp` or any package. Unit tests **mock** all network (`urllib`/`subprocess`) and yt-dlp; integration tests **skip** when the network or yt-dlp is absent. A shell-capable subagent installs nothing; verification is read-only + pytest.
- **The `any` lane is legally gray and opt-in by design** — never the default, always logs a responsibility line, records `license="unknown (any lane)"`. The tool author accepts responsibility; do not add value judgments, and do not weaken the transparency (log + sidecar).
- **Two `mood` modules** (unchanged from the mood-match slice): the pure core `scripts/lib/mood.py` (`from scripts.lib import mood`) and the local-folder driver `scripts/mood.py` (`from scripts import mood`). This slice adds `scripts/lib/catalog.py`, `scripts/lib/fetch.py`, `scripts/music_find.py`, `scripts/music_fetch.py` — none clash.

---

## Task 0: `catalog.Candidate` wire-contract + `SOURCES` + `slug`

**Files:**
- Create: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_catalog.py
import pytest

from scripts.lib.catalog import Candidate, SOURCES


def test_candidate_roundtrip_and_slug():
    c = Candidate(title="Blinding Lights", artist="The Weeknd", source="youtube",
                  ref="https://y/abc", license="unknown (any lane)", preview_url=None)
    assert c.to_dict()["title"] == "Blinding Lights"
    assert Candidate.from_dict(c.to_dict()) == c
    assert c.slug() == "youtube-the-weeknd-blinding-lights"


def test_candidate_rejects_empty_field():
    with pytest.raises(ValueError, match=r"Candidate.title.*non-empty"):
        Candidate(title="", artist="a", source="youtube", ref="r", license="l", preview_url=None)


def test_candidate_rejects_unknown_source():
    with pytest.raises(ValueError, match=r"source.*not in"):
        Candidate(title="t", artist="a", source="soundcloud", ref="r", license="l", preview_url=None)


def test_candidate_preview_url_optional_but_nonempty_when_present():
    assert Candidate("t", "a", "itunes", "r", "l", "http://p").preview_url == "http://p"
    with pytest.raises(ValueError, match="preview_url"):
        Candidate("t", "a", "itunes", "r", "l", "   ")


def test_sources_are_the_five_lanes():
    assert SOURCES == ("jamendo", "ccmixter", "youtube", "itunes", "deezer")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.catalog`.

- [ ] **Step 3: Write the minimal implementation**

```python
# scripts/lib/catalog.py
"""Discovery boundary for music sourcing (design docs/specs/2026-07-14-music-sourcing-design.md,
§4). Turns a mood query into Candidates across rights lanes — `free` (ccMixter no-key /
Jamendo when keyed) and `any` (YouTube via yt-dlp, iTunes/Deezer opt-in). All network is
isolated in per-source helpers (stdlib urllib for JSON, a yt-dlp module subprocess for
YouTube) so the ranking driver and the mood engine never touch the transport."""
import re
from dataclasses import dataclass

SOURCES = ("jamendo", "ccmixter", "youtube", "itunes", "deezer")


@dataclass(frozen=True)
class Candidate:
    title: str
    artist: str
    source: str                 # ∈ SOURCES
    ref: str                    # source-native id/url fetch resolves against
    license: str
    preview_url: str | None     # HTTP-fetchable 30s clip, or None → yt-dlp section

    def __post_init__(self) -> None:
        for name in ("title", "artist", "source", "ref", "license"):
            v = getattr(self, name)
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"Candidate.{name} must be a non-empty string, got {v!r}")
        if self.source not in SOURCES:
            raise ValueError(f"Candidate.source {self.source!r} not in {SOURCES}")
        if self.preview_url is not None and not (isinstance(self.preview_url, str)
                                                 and self.preview_url.strip()):
            raise ValueError(f"Candidate.preview_url must be a non-empty string or None, "
                             f"got {self.preview_url!r}")

    def slug(self) -> str:
        raw = f"{self.source}-{self.artist}-{self.title}".lower()
        return re.sub(r"[^a-z0-9]+", "-", raw).strip("-")[:80] or "track"

    def to_dict(self) -> dict:
        return {"title": self.title, "artist": self.artist, "source": self.source,
                "ref": self.ref, "license": self.license, "preview_url": self.preview_url}

    @classmethod
    def from_dict(cls, d: dict) -> "Candidate":
        missing = [k for k in ("title", "artist", "source", "ref", "license") if k not in d]
        if missing:
            raise ValueError(f"Candidate.from_dict missing key(s) {missing} — a candidate "
                             f"needs title, artist, source, ref, license")
        return cls(title=d["title"], artist=d["artist"], source=d["source"], ref=d["ref"],
                   license=d["license"], preview_url=d.get("preview_url"))
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog.Candidate wire-contract + SOURCES + slug (5.5 sourcing)"
```

---

## Task 1: catalog infra — `has_ytdlp`/`ytdlp_cmd`, Jamendo key, `_free_source`, HTTP helpers

**Files:**
- Modify: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_catalog.py
from scripts.lib import catalog


def test_free_source_is_ccmixter_without_key(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    monkeypatch.setattr(catalog, "_SOURCING_ENV", tmp_path / "sourcing.env")  # absent
    assert catalog._free_source() == "ccmixter"


def test_free_source_is_jamendo_with_env_key(monkeypatch):
    monkeypatch.setenv("JAMENDO_CLIENT_ID", "abc123")
    assert catalog._free_source() == "jamendo"


def test_free_source_reads_config_file(tmp_path, monkeypatch):
    monkeypatch.delenv("JAMENDO_CLIENT_ID", raising=False)
    env = tmp_path / "sourcing.env"
    env.write_text("JAMENDO_CLIENT_ID=fromfile\n")
    monkeypatch.setattr(catalog, "_SOURCING_ENV", env)
    assert catalog._jamendo_client_id() == "fromfile"
    assert catalog._free_source() == "jamendo"


def test_ytdlp_cmd_raises_when_absent(monkeypatch):
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: False)
    with pytest.raises(ValueError, match="setup.sh --with-sourcing"):
        catalog.ytdlp_cmd()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: module 'scripts.lib.catalog' has no attribute '_free_source'`.

- [ ] **Step 3: Add the infra** (imports at top of `catalog.py`, helpers after `Candidate`)

Add to the import block:

```python
import importlib.util
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
```

Add module constants under `SOURCES`:

```python
_UA = "video-grid/1.0 (music sourcing)"       # some catalog APIs 403 an empty User-Agent
_TIMEOUT = 20
_SOURCING_ENV = Path(__file__).resolve().parents[2] / "config" / "sourcing.env"  # repo-root/config
```

Add the helpers:

```python
def has_ytdlp() -> bool:
    """True if the yt-dlp module is importable in this interpreter (the any-lane gate).
    Mirrors vocals.has_demucs — a spec probe, invoked as a module so the venv's copy is
    found regardless of PATH."""
    return importlib.util.find_spec("yt_dlp") is not None


def ytdlp_cmd() -> list[str]:
    """The base yt-dlp invocation ([python, -m, yt_dlp]); raises the fail-loud remedy when
    yt-dlp is absent (callers may gate on has_ytdlp() first — defense-in-depth)."""
    if not has_ytdlp():
        raise ValueError("yt-dlp is not installed — install it with "
                         "`bash setup.sh --with-sourcing` (opt-in; the any lane needs it)")
    return [sys.executable, "-m", "yt_dlp"]


def _jamendo_client_id() -> str | None:
    """The Jamendo client_id from $JAMENDO_CLIENT_ID, else the gitignored config/sourcing.env
    that setup.sh writes. A public read-only app id, not a secret — but per-user."""
    cid = os.environ.get("JAMENDO_CLIENT_ID")
    if cid:
        return cid
    if _SOURCING_ENV.exists():
        for line in _SOURCING_ENV.read_text().splitlines():
            if line.startswith("JAMENDO_CLIENT_ID="):
                return line.split("=", 1)[1].strip() or None
    return None


def _free_source() -> str:
    """Resolve the free-lane catalog: Jamendo when a client_id is configured, else the
    no-key ccMixter fallback. Never a hard fail — the free lane must not dead-end."""
    return "jamendo" if _jamendo_client_id() else "ccmixter"


def _get_json(url: str):
    """GET a URL → parsed JSON (dict or list). Raises ValueError on any transport/parse
    error (fail loud — the driver surfaces it; never a silent empty shortlist)."""
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        raise ValueError(f"music sourcing: request to {url} failed ({e}) — "
                         f"check the network / that the catalog is reachable") from e


def http_download(url: str, dest: Path) -> None:
    """Stream a URL to `dest` (the free-lane direct download + the HTTP preview path)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp, open(dest, "wb") as f:
            shutil.copyfileobj(resp, f)
    except (urllib.error.URLError, TimeoutError) as e:
        raise ValueError(f"music sourcing: download of {url} failed ({e})") from e
```

Also add `import os` to the import block (used by `_jamendo_client_id`).

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: PASS (9 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog infra — yt-dlp gate, Jamendo key, free-source resolve, HTTP (5.5 sourcing)"
```

---

## Task 2: keyless catalogs — `_search_itunes` + `_search_deezer`

**Files:**
- Modify: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_catalog.py
import json as _json


class _FakeResp:
    def __init__(self, body): self._body = body.encode()
    def read(self): return self._body
    def __enter__(self): return self
    def __exit__(self, *a): return False


def _mock_urlopen(monkeypatch, body):
    monkeypatch.setattr(catalog.urllib.request, "urlopen",
                        lambda req, timeout=0: _FakeResp(_json.dumps(body)))


def test_search_itunes_parses(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [
        {"trackName": "Sun", "artistName": "Nova", "previewUrl": "http://p/1",
         "trackViewUrl": "http://itunes/1"}]})
    cands = catalog._search_itunes("energetic", 5)
    assert cands[0].source == "itunes" and cands[0].title == "Sun"
    assert cands[0].ref == "Nova - Sun" and cands[0].preview_url == "http://p/1"


def test_search_deezer_parses(monkeypatch):
    _mock_urlopen(monkeypatch, {"data": [
        {"title": "Rain", "artist": {"name": "Cloud"}, "preview": "http://p/2"}]})
    cands = catalog._search_deezer("chill", 5)
    assert cands[0].source == "deezer" and cands[0].ref == "Cloud - Rain"


def test_search_itunes_skips_incomplete_rows(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [{"trackName": "NoArtist"}]})
    assert catalog._search_itunes("x", 5) == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k "itunes or deezer" -q ; echo "EXIT: $?"`
Expected: FAIL — `AttributeError: ... '_search_itunes'`.

- [ ] **Step 3: Add the two keyless searches**

```python
def _search_itunes(query: str, n: int) -> list[Candidate]:
    url = ("https://itunes.apple.com/search?"
           + urllib.parse.urlencode({"term": query, "entity": "song", "limit": n}))
    out = []
    for r in _get_json(url).get("results", []):
        title, artist = r.get("trackName"), r.get("artistName")
        if not (title and artist):
            continue
        out.append(Candidate(title=title, artist=artist, source="itunes",
                             ref=f"{artist} - {title}", license="unknown (any lane)",
                             preview_url=r.get("previewUrl")))
    return out


def _search_deezer(query: str, n: int) -> list[Candidate]:
    url = "https://api.deezer.com/search?" + urllib.parse.urlencode({"q": query, "limit": n})
    out = []
    for r in _get_json(url).get("data", []):
        title, artist = r.get("title"), (r.get("artist") or {}).get("name")
        if not (title and artist):
            continue
        out.append(Candidate(title=title, artist=artist, source="deezer",
                             ref=f"{artist} - {title}", license="unknown (any lane)",
                             preview_url=r.get("preview")))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k "itunes or deezer" -q ; echo "EXIT: $?"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog keyless searches — iTunes + Deezer (5.5 sourcing)"
```

---

## Task 3: free catalogs — `_search_jamendo` + `_search_ccmixter`

**Files:**
- Modify: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_catalog.py
def test_search_jamendo_parses_and_needs_key(monkeypatch):
    monkeypatch.setattr(catalog, "_jamendo_client_id", lambda: None)
    with pytest.raises(ValueError, match="Jamendo client_id"):
        catalog._search_jamendo("epic", 5)
    monkeypatch.setattr(catalog, "_jamendo_client_id", lambda: "cid")
    _mock_urlopen(monkeypatch, {"results": [
        {"name": "Rise", "artist_name": "Aurora", "audio": "http://a/s",
         "audiodownload": "http://a/dl", "license_ccurl": "http://cc/by"}]})
    cands = catalog._search_jamendo("epic", 5)
    assert cands[0].source == "jamendo" and cands[0].ref == "http://a/dl"
    assert cands[0].license == "http://cc/by" and cands[0].preview_url == "http://a/s"


def test_search_ccmixter_parses_list(monkeypatch):
    _mock_urlopen(monkeypatch, [
        {"upload_name": "Groove", "user_name": "dj", "license_name": "CC BY",
         "files": [{"download_url": "http://c/dl"}]}])
    cands = catalog._search_ccmixter("funk", 5)
    assert cands[0].source == "ccmixter" and cands[0].ref == "http://c/dl"
    assert cands[0].license == "CC BY"
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k "jamendo or ccmixter" -q ; echo "EXIT: $?"`
Expected: FAIL — missing `_search_jamendo`.

- [ ] **Step 3: Add the two free searches**

```python
def _search_jamendo(query: str, n: int) -> list[Candidate]:
    cid = _jamendo_client_id()
    if not cid:
        raise ValueError("_search_jamendo needs a Jamendo client_id — set JAMENDO_CLIENT_ID "
                         "or run `bash setup.sh --with-sourcing` (else the ccMixter fallback runs)")
    url = ("https://api.jamendo.com/v3.0/tracks/?"
           + urllib.parse.urlencode({"client_id": cid, "format": "json", "limit": n,
                                     "fuzzytags": query, "audioformat": "mp32",
                                     "include": "musicinfo licenses"}))
    out = []
    for r in _get_json(url).get("results", []):
        title, artist = r.get("name"), r.get("artist_name")
        dl = r.get("audiodownload") or r.get("audio")
        if not (title and artist and dl):
            continue
        out.append(Candidate(title=title, artist=artist, source="jamendo", ref=dl,
                             license=r.get("license_ccurl") or "Creative Commons (Jamendo)",
                             preview_url=r.get("audio")))
    return out


def _search_ccmixter(query: str, n: int) -> list[Candidate]:
    url = ("http://dig.ccmixter.org/api/query?"
           + urllib.parse.urlencode({"f": "json", "limit": n, "tags": query}))
    data = _get_json(url)
    out = []
    for r in (data if isinstance(data, list) else []):
        title, artist = r.get("upload_name"), r.get("user_name")
        files = r.get("files") or []
        dl = files[0].get("download_url") if files else None
        if not (title and artist and dl):
            continue
        out.append(Candidate(title=title, artist=artist, source="ccmixter", ref=dl,
                             license=r.get("license_name") or "Creative Commons (ccMixter)",
                             preview_url=dl))
    return out
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k "jamendo or ccmixter" -q ; echo "EXIT: $?"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog free searches — Jamendo + ccMixter (5.5 sourcing)"
```

---

## Task 4: `_search_youtube` + the `search()` dispatcher (rights invariant)

**Files:**
- Modify: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_catalog.py
import subprocess as _sp


def _mock_ytdlp(monkeypatch, stdout, rc=0):
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    monkeypatch.setattr(catalog.subprocess, "run",
                        lambda *a, **k: _sp.CompletedProcess(a, rc, stdout, ""))


def test_search_youtube_parses_flat_json(monkeypatch):
    _mock_ytdlp(monkeypatch, '{"title": "Hype", "url": "vid1", "channel": "Ch"}\n')
    cands = catalog._search_youtube("hype", 3)
    assert cands[0].source == "youtube" and cands[0].ref == "vid1"
    assert cands[0].preview_url is None and cands[0].license == "unknown (any lane)"


def test_search_free_never_returns_youtube(monkeypatch):
    monkeypatch.setattr(catalog, "_free_source", lambda: "ccmixter")
    _mock_urlopen(monkeypatch, [{"upload_name": "G", "user_name": "u",
                                 "files": [{"download_url": "http://c/dl"}]}])
    cands = catalog.search("free", "funk", 3)
    assert all(c.source != "youtube" for c in cands)   # rights invariant


def test_search_any_defaults_to_youtube(monkeypatch):
    _mock_ytdlp(monkeypatch, '{"title": "T", "url": "v", "channel": "C"}\n')
    assert catalog.search("any", "x", 1)[0].source == "youtube"


def test_search_any_catalog_itunes(monkeypatch):
    _mock_urlopen(monkeypatch, {"results": [{"trackName": "S", "artistName": "A"}]})
    assert catalog.search("any", "x", 1, catalog="itunes")[0].source == "itunes"


def test_search_rejects_local_mode(monkeypatch):
    with pytest.raises(ValueError, match="local is the music-match lane"):
        catalog.search("local", "x", 1)


def test_search_zero_candidates_raises(monkeypatch):
    _mock_ytdlp(monkeypatch, "")
    with pytest.raises(ValueError, match="no candidates"):
        catalog.search("any", "zzz", 3)
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k "youtube or search" -q ; echo "EXIT: $?"`
Expected: FAIL — missing `_search_youtube`/`search`.

- [ ] **Step 3: Add the YouTube search + the dispatcher**

```python
def _search_youtube(query: str, n: int) -> list[Candidate]:
    proc = subprocess.run(
        ytdlp_cmd() + [f"ytsearch{n}:{query}", "--flat-playlist", "--dump-json", "--no-warnings"],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"music sourcing: yt-dlp search failed ({proc.stderr.strip()})")
    out = []
    for line in proc.stdout.splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        title = r.get("title")
        ref = r.get("webpage_url") or r.get("url") or r.get("id")
        if not (title and ref):
            continue
        out.append(Candidate(title=title, artist=r.get("channel") or r.get("uploader") or "unknown",
                             source="youtube", ref=ref, license="unknown (any lane)",
                             preview_url=None))
    return out


def search(mode: str, query: str, n: int, catalog: str | None = None) -> list[Candidate]:
    """Discovery across rights lanes (design §4). `free` → _free_source() (ccMixter / Jamendo);
    `any` → YouTube by default, or `catalog` in {itunes, deezer}. Rights invariant: the free
    branch only ever calls the CC catalogs, never YouTube. Zero results raises."""
    if mode == "free":
        cands = (_search_jamendo(query, n) if _free_source() == "jamendo"
                 else _search_ccmixter(query, n))
    elif mode == "any":
        if catalog == "itunes":
            cands = _search_itunes(query, n)
        elif catalog == "deezer":
            cands = _search_deezer(query, n)
        elif catalog in (None, "youtube"):
            cands = _search_youtube(query, n)
        else:
            raise ValueError(f"--catalog {catalog!r} not in (youtube, itunes, deezer)")
    else:
        raise ValueError(f"music sourcing mode {mode!r} not in (free, any) — "
                         f"local is the music-match lane, not sourcing")
    if not cands:
        raise ValueError(f"music sourcing: no candidates for {query!r} (mode={mode}) — "
                         f"try a different --query or --mood")
    return cands
```

Note: the `catalog` parameter shadows the module name inside `search`; that is intentional and local (the function references no module-level `catalog`). Keep it.

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: PASS (whole file).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog YouTube search + search() dispatcher w/ rights invariant (5.5 sourcing)"
```

---

## Task 5: `preview_clip` — HTTP-or-yt-dlp-section

**Files:**
- Modify: `scripts/lib/catalog.py`
- Test: `tests/lib/test_catalog.py`

- [ ] **Step 1: Write the failing test**

```python
# append to tests/lib/test_catalog.py
def test_preview_clip_http_when_preview_url(tmp_path, monkeypatch):
    c = Candidate("t", "a", "itunes", "a - t", "unknown (any lane)", "http://p/x.mp3")
    monkeypatch.setattr(catalog, "http_download",
                        lambda url, dest: dest.write_bytes(b"AUDIO"))
    path = catalog.preview_clip(c, str(tmp_path))
    assert path.endswith(".preview.mp3") and open(path, "rb").read() == b"AUDIO"


def test_preview_clip_ytdlp_section_when_no_preview(tmp_path, monkeypatch):
    c = Candidate("t", "a", "youtube", "vid", "unknown (any lane)", None)
    monkeypatch.setattr(catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    def fake_run(cmd, **k):
        (tmp_path / f"{c.slug()}.preview.m4a").write_bytes(b"YT")
        return _sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(catalog.subprocess, "run", fake_run)
    path = catalog.preview_clip(c, str(tmp_path))
    assert path.endswith(".preview.m4a")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -k preview -q ; echo "EXIT: $?"`
Expected: FAIL — missing `preview_clip`.

- [ ] **Step 3: Add `preview_clip`**

```python
def preview_clip(candidate: Candidate, cache_dir: str) -> str:
    """Materialise a ~30 s clip for mood analysis, source-appropriately (design §4): an
    HTTP preview_url via GET, else a yt-dlp 0:00–0:30 section. Returns the clip path."""
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    slug = candidate.slug()
    if candidate.preview_url:
        dest = cache / f"{slug}.preview.mp3"
        http_download(candidate.preview_url, dest)
        return str(dest)
    proc = subprocess.run(
        ytdlp_cmd() + ["-f", "bestaudio", "--download-sections", "*0:00-0:30",
                       "-o", str(cache / f"{slug}.preview.%(ext)s"), "--no-warnings",
                       candidate.ref],
        capture_output=True, text=True)
    if proc.returncode != 0:
        raise ValueError(f"music sourcing: yt-dlp preview failed ({proc.stderr.strip()})")
    hits = sorted(cache.glob(f"{slug}.preview.*"))
    if not hits:
        raise ValueError(f"music sourcing: yt-dlp produced no preview for {candidate.ref}")
    return str(hits[0])
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_catalog.py -q ; echo "EXIT: $?"`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/catalog.py tests/lib/test_catalog.py
git commit -m "feat: catalog.preview_clip — HTTP preview or yt-dlp section (5.5 sourcing)"
```

---

## Task 6: `fetch.py` — `FetchedTrack` + `download` (cache, sidecar, responsibility log, rights guard)

**Files:**
- Create: `scripts/lib/fetch.py`
- Test: `tests/lib/test_fetch.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_fetch.py
import json
import subprocess as _sp

import pytest

from scripts.lib import catalog, fetch


def _cc(**kw):
    d = dict(title="T", artist="A", source="jamendo", ref="http://a/dl",
             license="CC BY", preview_url=None)
    d.update(kw)
    return catalog.Candidate(**d)


def test_download_free_direct_writes_file_and_sidecar(tmp_path, monkeypatch):
    monkeypatch.setattr(fetch.catalog, "http_download",
                        lambda url, dest: dest.write_bytes(b"MP3"))
    tr = fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    assert open(tr.path, "rb").read() == b"MP3" and tr.license == "CC BY"
    side = json.loads((tmp_path / f"{_cc().slug()}.json").read_text())
    assert side["source"] == "jamendo" and side["date"] == "2026-07-14"


def test_download_any_youtube_logs_responsibility(tmp_path, monkeypatch, capsys):
    c = _cc(source="youtube", ref="vid", license="unknown (any lane)")
    monkeypatch.setattr(fetch.catalog, "has_ytdlp", lambda: True)
    monkeypatch.setattr(fetch.catalog, "ytdlp_cmd", lambda: ["yt-dlp"])
    def fake_run(cmd, **k):
        (tmp_path / f"{c.slug()}.m4a").write_bytes(b"YT")
        return _sp.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(fetch.subprocess, "run", fake_run)
    tr = fetch.download(c, "any", str(tmp_path), "2026-07-14")
    assert tr.path.endswith(".m4a")
    assert "COPYRIGHTED" in capsys.readouterr().err        # responsibility log


def test_download_free_does_not_log_responsibility(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fetch.catalog, "http_download", lambda url, dest: dest.write_bytes(b"x"))
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    assert "COPYRIGHTED" not in capsys.readouterr().err


def test_download_reuses_cache(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(fetch.catalog, "http_download",
                        lambda url, dest: (calls.append(1), dest.write_bytes(b"x")))
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")
    fetch.download(_cc(), "free", str(tmp_path), "2026-07-14")   # sidecar present → reuse
    assert len(calls) == 1


def test_download_free_rejects_youtube_source(tmp_path):
    with pytest.raises(ValueError, match="rights invariant"):
        fetch.download(_cc(source="youtube", ref="v", license="unknown (any lane)"),
                       "free", str(tmp_path), "2026-07-14")
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_fetch.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: scripts.lib.fetch`.

- [ ] **Step 3: Write `fetch.py`**

```python
# scripts/lib/fetch.py
"""Download boundary for music sourcing (design §5). Resolves a chosen Candidate to a
cached audio file + a metadata sidecar, per rights lane: `free` (Jamendo/ccMixter) is a
direct HTTP GET; `any` (YouTube / iTunes / Deezer name) goes through yt-dlp and logs a
responsibility line. Mirrors vocals.py — the opt-in heavy tool (yt-dlp) sits behind
catalog.has_ytdlp() with a fail-loud remedy. The driver stamps `date` (no ambient clock)."""
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from scripts.lib import catalog


@dataclass(frozen=True)
class FetchedTrack:
    path: str
    title: str
    artist: str
    source: str
    source_url: str
    license: str
    date: str

    def __post_init__(self) -> None:
        for name in ("path", "title", "artist", "source", "source_url", "license", "date"):
            v = getattr(self, name)
            if not (isinstance(v, str) and v.strip()):
                raise ValueError(f"FetchedTrack.{name} must be a non-empty string, got {v!r}")

    def sidecar(self) -> dict:
        return {"title": self.title, "artist": self.artist, "source": self.source,
                "source_url": self.source_url, "license": self.license, "date": self.date}


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _cached(cache: Path, slug: str) -> Path | None:
    hits = sorted(p for p in cache.glob(f"{slug}.*") if p.suffix != ".json")
    return hits[0] if hits else None


def download(candidate: catalog.Candidate, mode: str, cache_dir: str, date: str) -> FetchedTrack:
    """Download `candidate` to `cache_dir` and write its sidecar. `free` → direct HTTP;
    `any` → yt-dlp (+ responsibility log). A cached slug (sidecar present) is reused."""
    if mode not in ("free", "any"):
        raise ValueError(f"fetch mode {mode!r} not in (free, any)")
    if mode == "free" and candidate.source not in ("jamendo", "ccmixter"):
        raise ValueError(f"free lane cannot fetch a {candidate.source} source — rights invariant")
    cache = Path(cache_dir); cache.mkdir(parents=True, exist_ok=True)
    slug = candidate.slug()
    sidecar = cache / f"{slug}.json"
    if sidecar.exists() and (hit := _cached(cache, slug)) is not None:
        meta = json.loads(sidecar.read_text())
        _log(f"music_fetch: reusing cached {hit.name}")
        return FetchedTrack(path=str(hit), title=meta["title"], artist=meta["artist"],
                            source=meta["source"], source_url=meta["source_url"],
                            license=meta["license"], date=meta["date"])
    if candidate.source in ("jamendo", "ccmixter"):
        dest = cache / f"{slug}.mp3"
        catalog.http_download(candidate.ref, dest)
        path = dest
    else:                                        # youtube / itunes / deezer → yt-dlp (any lane)
        target = candidate.ref if candidate.source == "youtube" else f"ytsearch1:{candidate.ref}"
        _log(f"music_fetch: mode=any: downloading COPYRIGHTED audio via yt-dlp from "
             f"{target!r}. Licensing/rights are the user's responsibility and "
             f"jurisdiction-dependent (recorded in {sidecar.name}).")
        proc = subprocess.run(
            catalog.ytdlp_cmd() + ["-f", "bestaudio", "-o", str(cache / f"{slug}.%(ext)s"),
                                   "--no-warnings", target],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise ValueError(f"music sourcing: yt-dlp download failed ({proc.stderr.strip()})")
        path = _cached(cache, slug)
        if path is None:
            raise ValueError(f"music sourcing: yt-dlp produced no file for {target}")
    track = FetchedTrack(path=str(path), title=candidate.title, artist=candidate.artist,
                         source=candidate.source, source_url=candidate.ref,
                         license=candidate.license, date=date)
    sidecar.write_text(json.dumps(track.sidecar(), indent=2))
    return track
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_fetch.py -q ; echo "EXIT: $?"`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/lib/fetch.py tests/lib/test_fetch.py
git commit -m "feat: fetch.download — cache, sidecar, responsibility log, rights guard (5.5 sourcing)"
```

---

## Task 7: `music_find.py` driver — `build_shortlist` + `_to_markdown` + CLI

**Files:**
- Create: `scripts/music_find.py`
- Test: `tests/lib/test_music_find_driver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_music_find_driver.py
"""music_find driver — mocks catalog.search/preview_clip + beats.mood_features (no network,
no librosa here). Mirrors test_mood_driver.py."""
import json

import pytest

from scripts import music_find as find
from scripts.lib.catalog import Candidate
from scripts.lib.mood import MoodVector


def _stub(monkeypatch, cands, vecs):
    monkeypatch.setattr(find.catalog, "search", lambda *a, **k: cands)
    monkeypatch.setattr(find.catalog, "preview_clip", lambda c, d: c.slug())
    monkeypatch.setattr(find.beats, "mood_features", lambda slug: vecs[slug])


def _c(title, source="youtube"):
    return Candidate(title, "A", source, "ref-" + title, "unknown (any lane)", None)


def test_build_shortlist_ranks_and_writes(tmp_path, monkeypatch):
    e, c = _c("Energetic"), _c("Chill")
    _stub(monkeypatch, [e, c],
          {e.slug(): MoodVector(0.9, 0.7, 0.85), c.slug(): MoodVector(0.2, 0.5, 0.3)})
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "energetic", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["mode"] == "any" and data["fallback"] is None
    assert [r["title"] for r in data["candidates"]] == ["Energetic", "Chill"]
    assert "fit" in data["candidates"][0] and data["candidates"][0]["source"] == "youtube"
    assert (out / "MUSIC_SHORTLIST.md").exists()


def test_build_shortlist_unknown_mood_falls_back_to_drive(tmp_path, monkeypatch, capsys):
    a, b = _c("A"), _c("B")
    _stub(monkeypatch, [a, b],
          {a.slug(): MoodVector(0.1, 0.5, 0.1), b.slug(): MoodVector(0.9, 0.5, 0.9)})
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "purple wombat", str(out))
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["fallback"] == "drive" and data["candidates"][0]["title"] == "B"
    assert "drive" in data["candidates"][0] and "distance" not in data["candidates"][0]
    assert "ranking by drive" in capsys.readouterr().err


def test_cli_reads_mood_from_spec(tmp_path, monkeypatch):
    from scripts.lib.spec import Spec
    x = _c("X")
    _stub(monkeypatch, [x], {x.slug(): MoodVector(0.9, 0.7, 0.85)})
    spec = tmp_path / "SPEC.json"
    Spec(canvas=(1080, 1920), length_s=30.0, mood="energetic", hook="h").write(spec)
    out = tmp_path / "out"; out.mkdir()
    monkeypatch.setattr("sys.argv", ["music_find", "--mode", "any", "--spec", str(spec),
                                     "--out-dir", str(out)])
    find.main()
    assert json.loads((out / "MUSIC_SHORTLIST.json").read_text())["mood_text"] == "energetic"


def test_cli_requires_free_or_any(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["music_find", "--mode", "local", "--mood", "x",
                                     "--out-dir", str(tmp_path)])
    with pytest.raises(SystemExit):        # choices=(free, any) → argparse rejects local
        find.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_music_find_driver.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: scripts.music_find`.

- [ ] **Step 3: Write `music_find.py`**

```python
# scripts/music_find.py
"""music sourcing — find (design §4): query a catalog by SPEC.mood, mood-analyse each
candidate's preview locally (beats.mood_features + the pure mood.rank core), write
MUSIC_SHORTLIST.{json,md} for the agent to pick from. A thin driver over scripts/lib/catalog
(the network boundary) + scripts/lib/mood (the pure scorer) — the same ranking as the local
lane, candidates just come from the network instead of a folder."""
import argparse
import json
import sys
import tempfile
from pathlib import Path

from scripts import beats
from scripts.lib import catalog, mood
from scripts.lib.spec import Spec


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def build_shortlist(mode: str, mood_text: str, out_dir: str, *, n: int = 8,
                    query: str | None = None, cat: str | None = None) -> dict:
    """Discover n candidates (per rights lane), rank by fit to mood_text, write
    MUSIC_SHORTLIST.{json,md} in out_dir. Zero candidates raises (in catalog.search); an
    unknown mood logs and falls back to drive-ranking (never silent)."""
    cands = catalog.search(mode, query or mood_text, n, catalog=cat)
    by_slug = {c.slug(): c for c in cands}
    with tempfile.TemporaryDirectory() as clips:
        pairs = [(c.slug(), beats.mood_features(catalog.preview_clip(c, clips))) for c in cands]
    target = mood.mood_target(mood_text)
    if target is None:
        _log(f"music-source: '{mood_text}' matched no mood anchor "
             f"({', '.join(sorted(mood.MOOD_ANCHORS))}) — ranking by drive (energy+pace)")
        ranked = mood.rank_by_drive(pairs)
        head = {"target": None, "fallback": "drive"}
    else:
        ranked = mood.rank(pairs, target)
        head = {"target": target.to_dict(), "fallback": None}
    rows = []
    for slug, score, v in ranked:
        c = by_slug[slug]
        row = {"title": c.title, "artist": c.artist, "source": c.source, "ref": c.ref,
               "license": c.license, "preview_url": c.preview_url, "vector": v.to_dict()}
        if head["fallback"] == "drive":
            row["drive"] = round(score, 4)
        else:
            row["distance"] = round(score, 4)
            row["fit"] = round(1.0 / (1.0 + score), 4)
        rows.append(row)
    payload = {"mood_text": mood_text, "mode": mode, **head, "candidates": rows}
    out = Path(out_dir)
    json_path, md_path = out / "MUSIC_SHORTLIST.json", out / "MUSIC_SHORTLIST.md"
    json_path.write_text(json.dumps(payload, indent=2))
    md_path.write_text(_to_markdown(payload))
    return {"json": str(json_path), "md": str(md_path), "ranked": ranked}


def _to_markdown(payload: dict) -> str:
    if payload["fallback"] == "drive":
        sub = "_no mood anchor matched — ranked by drive (energy+pace)_"
    else:
        t = payload["target"]
        sub = (f"_target: energy {t['energy']:.2f} · brightness {t['brightness']:.2f} "
               f"· pace {t['pace']:.2f}_")
    lines = [f"# Music shortlist — mood: {payload['mood_text']} (mode: {payload['mode']})",
             "", sub, "",
             "| # | title | artist | source | fit | energy | brightness | pace | license |",
             "|--:|-------|--------|--------|----:|-------:|-----------:|-----:|---------|"]
    for i, c in enumerate(payload["candidates"], 1):
        v = c["vector"]
        fit = f"{c['fit']:.2f}" if "fit" in c else f"drive {c['drive']:.2f}"
        lines.append(f"| {i} | {c['title']} | {c['artist']} | {c['source']} | {fit} | "
                     f"{v['energy']:.2f} | {v['brightness']:.2f} | {v['pace']:.2f} | {c['license']} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="source candidate tracks by mood → MUSIC_SHORTLIST.{json,md}")
    ap.add_argument("--mode", required=True, choices=("free", "any"),
                    help="rights lane (free = CC; any = incl. copyrighted via yt-dlp)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--spec", help="SPEC.json — reads its mood field")
    g.add_argument("--mood", help="mood text directly (e.g. 'energetic')")
    ap.add_argument("--query", help="override the catalog search query (default: the mood text)")
    ap.add_argument("--n", type=int, default=8, help="candidate count (default 8)")
    ap.add_argument("--catalog", choices=("youtube", "itunes", "deezer"),
                    help="any-lane catalog (default youtube)")
    ap.add_argument("--out-dir", required=True, help="where to write MUSIC_SHORTLIST.{json,md}")
    a = ap.parse_args()
    mood_text = Spec.from_json(a.spec).mood if a.spec else a.mood
    res = build_shortlist(a.mode, mood_text, a.out_dir, n=a.n, query=a.query, cat=a.catalog)
    print(res["json"])
    print(res["md"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_music_find_driver.py -q ; echo "EXIT: $?"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/music_find.py tests/lib/test_music_find_driver.py
git commit -m "feat: music_find driver — rank sourced previews → MUSIC_SHORTLIST (5.5 sourcing)"
```

---

## Task 8: `music_fetch.py` driver — `fetch_pick` / `fetch_named` + CLI

**Files:**
- Create: `scripts/music_fetch.py`
- Test: `tests/lib/test_music_fetch_driver.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/lib/test_music_fetch_driver.py
"""music_fetch driver — mocks fetch.download (no network). Asserts pick + explicit-name paths."""
import json

import pytest

from scripts import music_fetch as mf
from scripts.lib import catalog, fetch


def _shortlist(tmp_path):
    p = tmp_path / "MUSIC_SHORTLIST.json"
    p.write_text(json.dumps({"candidates": [
        {"title": "T1", "artist": "A", "source": "youtube", "ref": "v1",
         "license": "unknown (any lane)", "preview_url": None},
        {"title": "T2", "artist": "B", "source": "youtube", "ref": "v2",
         "license": "unknown (any lane)", "preview_url": None}]}))
    return p


def _fake_track(path="/cache/x.m4a"):
    return fetch.FetchedTrack(path=path, title="T", artist="A", source="youtube",
                              source_url="v", license="unknown (any lane)", date="2026-07-14")


def test_fetch_pick_downloads_selected_row(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(mf.fetch, "download",
                        lambda cand, mode, cd, date: seen.setdefault("ref", cand.ref) or _fake_track())
    mf.fetch_pick(str(_shortlist(tmp_path)), 2, "any", str(tmp_path), "2026-07-14")
    assert seen["ref"] == "v2"


def test_fetch_pick_out_of_range_raises(tmp_path):
    with pytest.raises(ValueError, match="out of range"):
        mf.fetch_pick(str(_shortlist(tmp_path)), 9, "any", str(tmp_path), "2026-07-14")


def test_fetch_named_resolves_top1(tmp_path, monkeypatch):
    monkeypatch.setattr(mf.catalog, "search",
                        lambda mode, q, n: [catalog.Candidate("Named", "A", "youtube", "vN",
                                                              "unknown (any lane)", None)])
    monkeypatch.setattr(mf.fetch, "download", lambda cand, mode, cd, date: _fake_track(cand.ref))
    tr = mf.fetch_named("some song", "any", str(tmp_path), "2026-07-14")
    assert tr.path == "vN"


def test_cli_from_shortlist_needs_pick(tmp_path, monkeypatch):
    monkeypatch.setattr("sys.argv", ["music_fetch", "--mode", "any", "--from-shortlist",
                                     str(_shortlist(tmp_path)), "--cache-dir", str(tmp_path),
                                     "--date", "2026-07-14"])
    with pytest.raises(SystemExit):        # --from-shortlist without --pick → ap.error
        mf.main()
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/lib/test_music_fetch_driver.py -q ; echo "EXIT: $?"`
Expected: FAIL — `ModuleNotFoundError: scripts.music_fetch`.

- [ ] **Step 3: Write `music_fetch.py`**

```python
# scripts/music_fetch.py
"""music sourcing — fetch (design §5): resolve a picked shortlist row (or an explicit
--track name) to a cached audio file + sidecar via scripts/lib/fetch. Prints the cached
path; the SKILL then runs `beats --auto-start` on it for MUSIC.json."""
import argparse
from pathlib import Path
import json

from scripts.lib import catalog, fetch


def fetch_pick(shortlist: str, pick: int, mode: str, cache_dir: str, date: str) -> fetch.FetchedTrack:
    """Fetch row `pick` (1-based) from a MUSIC_SHORTLIST.json."""
    rows = json.loads(Path(shortlist).read_text()).get("candidates", [])
    if not 1 <= pick <= len(rows):
        raise ValueError(f"--pick {pick} out of range 1..{len(rows)} for {shortlist}")
    r = rows[pick - 1]
    cand = catalog.Candidate(title=r["title"], artist=r["artist"], source=r["source"],
                             ref=r["ref"], license=r["license"], preview_url=r.get("preview_url"))
    return fetch.download(cand, mode, cache_dir, date)


def fetch_named(name: str, mode: str, cache_dir: str, date: str) -> fetch.FetchedTrack:
    """Fetch an explicit track name directly (no shortlist) — resolve the top-1 in the lane."""
    return fetch.download(catalog.search(mode, name, 1)[0], mode, cache_dir, date)


def main() -> None:
    ap = argparse.ArgumentParser(description="download a sourced track → cache + sidecar")
    ap.add_argument("--mode", required=True, choices=("free", "any"))
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--from-shortlist", help="MUSIC_SHORTLIST.json to pick from")
    g.add_argument("--track", help="explicit track name to resolve directly")
    ap.add_argument("--pick", type=int, help="1-based row of --from-shortlist")
    ap.add_argument("--cache-dir", required=True, help="cache dir (e.g. <run>/music/cache)")
    ap.add_argument("--date", required=True, help="YYYY-MM-DD stamp for the sidecar")
    a = ap.parse_args()
    if a.from_shortlist:
        if a.pick is None:
            ap.error("--from-shortlist needs --pick <row>")
        track = fetch_pick(a.from_shortlist, a.pick, a.mode, a.cache_dir, a.date)
    else:
        track = fetch_named(a.track, a.mode, a.cache_dir, a.date)
    print(track.path)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify it passes**

Run: `.venv/bin/python -m pytest tests/lib/test_music_fetch_driver.py -q ; echo "EXIT: $?"`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add scripts/music_fetch.py tests/lib/test_music_fetch_driver.py
git commit -m "feat: music_fetch driver — pick/named download + CLI (5.5 sourcing)"
```

---

## Task 9: integration — `test_sourcing.py` (skip-if-no-network iTunes + local-fixture find)

**Files:**
- Create: `tests/integration/test_sourcing.py`

- [ ] **Step 1: Write the tests**

```python
# tests/integration/test_sourcing.py
"""Sourcing integration (design §11): a real keyless iTunes smoke (skipped when the network
is down) + a fully-local find that runs REAL librosa mood on fixture WAVs with the catalog
stubbed — proving find → mood_features → rank end-to-end offline (the demucs-skip ethos)."""
import json

import numpy as np
import pytest
from scipy.io import wavfile

from scripts import music_find as find
from scripts.lib import catalog


def _mix_wav(path, sr, secs, freq, bpm, amp):
    t = np.arange(int(secs * sr)) / sr
    env = np.zeros_like(t)
    step = int(sr * 60.0 / bpm)
    for i in range(0, len(env), step):
        env[i:i + max(1, step // 4)] = 1.0
    wavfile.write(path, sr, (amp * np.sin(2 * np.pi * freq * t) * env).astype(np.float32))
    return str(path)


@pytest.mark.integration
def test_itunes_search_smoke_or_skip():
    try:
        cands = catalog._search_itunes("energetic electronic", 3)
    except ValueError as e:
        pytest.skip(f"no network for the iTunes smoke: {e}")
    assert cands and cands[0].source == "itunes"


@pytest.mark.integration
def test_find_local_fixture_ranks_energetic_first(tmp_path, monkeypatch):
    e = _mix_wav(tmp_path / "e.wav", 22050, 8, freq=5000, bpm=150, amp=0.9)   # bright + fast
    c = _mix_wav(tmp_path / "c.wav", 22050, 8, freq=250, bpm=70, amp=0.3)     # dark + slow
    cands = [catalog.Candidate("Energetic", "A", "youtube", "u-e", "unknown (any lane)", None),
             catalog.Candidate("Chill", "B", "youtube", "u-c", "unknown (any lane)", None)]
    clips = {cands[0].slug(): e, cands[1].slug(): c}
    monkeypatch.setattr(find.catalog, "search", lambda *a, **k: cands)
    monkeypatch.setattr(find.catalog, "preview_clip", lambda cand, d: clips[cand.slug()])
    out = tmp_path / "out"; out.mkdir()
    find.build_shortlist("any", "energetic", str(out))          # REAL beats.mood_features
    data = json.loads((out / "MUSIC_SHORTLIST.json").read_text())
    assert data["candidates"][0]["title"] == "Energetic"
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/integration/test_sourcing.py -q -m integration ; echo "EXIT: $?"`
Expected: PASS (the iTunes smoke may `skip` off-network; the local find PASSES via real librosa).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_sourcing.py
git commit -m "test: sourcing integration — iTunes smoke + local-fixture real-mood find (5.5 sourcing)"
```

---

## Task 10: `setup.sh --with-sourcing` (interactive free-lane key) + `.gitignore`

**Files:**
- Modify: `setup.sh:14-22` (arg-scan) and the venv-deps section (after the demucs block, ~line 134)
- Modify: `.gitignore`

> **No machine mutation:** edit the script only. Do **not** run `setup.sh`, do not `pip install yt-dlp`. Verification is reading the diff back.

- [ ] **Step 1: Add `--with-sourcing` to the arg-scan**

Change the comment + `WANT_*` line + the `case`:

```bash
# scan all args so --with-vidstab, --with-fonts, --with-demucs and --with-sourcing compose (order-independent)
WANT_VIDSTAB=0; WANT_FONTS=0; WANT_DEMUCS=0; WANT_SOURCING=0
for arg in "$@"; do
  case "$arg" in
    --with-vidstab)  WANT_VIDSTAB=1 ;;
    --with-fonts)    WANT_FONTS=1 ;;
    --with-demucs)   WANT_DEMUCS=1 ;;
    --with-sourcing) WANT_SOURCING=1 ;;
  esac
done
```

- [ ] **Step 2: Add the install + interactive free-lane block** (after the `WANT_DEMUCS` block, before the `mkdir -p "$SKILL_DIR/models"` line)

```bash
# music sourcing (§5.5 B3). Opt-in — installs yt-dlp (the `any` lane) and configures the
# free lane's OPTIONAL Jamendo key. The free lane works out of the box via ccMixter (no
# key), so this is capability, not a hard requirement. Guarded on already-installed so a
# rerun is a clean no-op (kept out of requirements.txt to keep the base install lean).
if [ "$WANT_SOURCING" = 1 ]; then
  "$VENV/bin/pip" show yt-dlp >/dev/null 2>&1 || {
    echo "installing yt-dlp (any-lane audio sourcing) into the venv..."
    "$VENV/bin/pip" install yt-dlp; }
  SRC_ENV="$SKILL_DIR/config/sourcing.env"
  if [ -z "${JAMENDO_CLIENT_ID:-}" ] && ! grep -qs '^JAMENDO_CLIENT_ID=' "$SRC_ENV" 2>/dev/null; then
    echo ""
    echo "Free-lane music source. Jamendo (richer CC catalog) needs a free client_id;"
    echo "without one the free lane uses ccMixter (no key)."
    echo "  [1] paste a Jamendo client_id   [2] open the devportal to create one   [3] use ccMixter"
    printf "choose [1/2/3] (default 3): "
    read -r choice || choice=3
    case "${choice:-3}" in
      1) printf "paste client_id: "; read -r cid
         mkdir -p "$SKILL_DIR/config"; echo "JAMENDO_CLIENT_ID=$cid" > "$SRC_ENV"
         echo "saved to config/sourcing.env (gitignored)" ;;
      2) echo "open https://devportal.jamendo.com/ , create an app, then re-run: bash setup.sh --with-sourcing"
         echo "(the free lane uses ccMixter until a key is configured)" ;;
      *) echo "using ccMixter (no key) for the free lane" ;;
    esac
  fi
fi
```

- [ ] **Step 3: gitignore the per-user config**

Append to `.gitignore`:

```
# per-user music-sourcing config (Jamendo client_id) — never committed
config/sourcing.env
```

- [ ] **Step 4: Verify (read-only — do NOT run setup.sh)**

Run: `bash -n setup.sh ; echo "SYNTAX EXIT: $?"` (syntax check only — no execution)
Run: `git diff --stat setup.sh .gitignore`
Expected: `bash -n` returns 0; the diff shows the two files changed.

- [ ] **Step 5: Commit**

```bash
git add setup.sh .gitignore
git commit -m "build: setup.sh --with-sourcing (yt-dlp + interactive Jamendo key) + gitignore config (5.5 sourcing)"
```

---

## Task 11: `music-source` SKILL + music-match cross-ref + using-montage wiring

**Files:**
- Create: `SKILLS/music-source/SKILL.md`
- Modify: `SKILLS/music-match/SKILL.md` (the "Not this skill / Sourcing" bullet)
- Modify: `SKILLS/using-montage/SKILL.md` (step 5 music routing)

- [ ] **Step 1: Write `SKILLS/music-source/SKILL.md`**

```markdown
---
name: music-source
description: Stage 5.5 (network lanes) — source the reel's track from the internet when the brief has a mood but no chosen track and no local folder. Discovers candidates (free = ccMixter/Jamendo CC; any = YouTube/iTunes/Deezer incl. copyrighted), ranks them by fit to SPEC.mood into MUSIC_SHORTLIST.md, you present the top few, the user picks, then it downloads the pick and beats --auto-start writes MUSIC.json. The any lane is copyrighted and legally gray — opt-in, user's responsibility.
---

# music-source (stage 5.5, network lanes)

Source a track from the internet + rank by mood, so the user picks from a short,
mood-sorted list instead of hunting a library. The **sibling of music-match**: same
ranking, candidates come from a catalog instead of the user's folder. This is the
**selection** pass; the chosen track still goes through `beats --auto-start` for the
final `MUSIC.json`.

**The ranking is numbers; the pick is judgment.** `music_find` scores each candidate's
preview (energy / brightness / pace) against `SPEC.mood`; you surface the top rows; the
user makes the final call (the §4.1 music checkpoint stays human-influenced).

## Rights lanes (`SPEC.music_mode`)

- **`free`** (default, safe for distribution) — Creative-Commons only. ccMixter (no key)
  by default; Jamendo (richer) when a `JAMENDO_CLIENT_ID` is configured. Direct legal
  download; every file records its CC license.
- **`any`** — includes **copyrighted** audio via yt-dlp (YouTube default; iTunes/Deezer
  with `--catalog`). **Legally gray and jurisdiction-dependent — opt-in, the user's
  responsibility.** Only use it when `SPEC.music_mode` is explicitly `any`. Every fetch
  logs a responsibility line and records `license="unknown (any lane)"`.

## Inputs

- **`SPEC.json`** (from reel-brief) — `mood`, `length_s`, `music_mode`. No SPEC? pass
  `--mood "..." --mode free|any`.
- **`yt-dlp`** is needed for the `any` lane — `bash setup.sh --with-sourcing` (opt-in).
  The `free` lane needs no install.

## Procedure

Announce on entry: **"Using music-source to source and shortlist the reel's track by mood."**

1. **Recon.** Read `SPEC.json` (note `mood`, `length_s`, `music_mode`). Confirm the lane
   with the user — and for `any`, confirm they accept the copyright/rights responsibility
   before sourcing.
2. **Find** (you type the flags; the user never does):
   `.venv/bin/python -m scripts.music_find --mode <free|any> --spec <run>/SPEC.json --out-dir <run>`
   (or `--mood "energetic"`; add `--catalog itunes` / `--n 12` / `--query "..."` to steer).
   It writes `<run>/MUSIC_SHORTLIST.md` + `.json`.
   - An **unrecognized mood** is not an error — it logs and ranks by drive (energy+pace);
     say so when you present the list.
   - **No candidates / no network / yt-dlp missing** fail loud — fix and re-run.
3. **Present** the top few `MUSIC_SHORTLIST.md` rows (rank · title · artist · source · fit ·
   axes · license). The user picks one — or asks to hear previews and picks by ear.
4. **Fetch** the pick:
   `.venv/bin/python -m scripts.music_fetch --mode <free|any> --from-shortlist <run>/MUSIC_SHORTLIST.json --pick <row> --cache-dir <run>/music/cache --date $(date +%F)`
   — prints the cached file path.
5. **Lock** it into `MUSIC.json`:
   `.venv/bin/python -m scripts.beats <cached-file> --auto-start --duration <length_s> --out <run>/MUSIC.json`
   — start-offset intelligence starts the reel on the strongest fragment, in a vocal
   pause. Pass `<run>/MUSIC.json` on to edit-plan.

## Not this skill

- **A local folder** the user already has → **music-match** (the `local` lane), not this.
- **Writing `MUSIC.json`** → `beats --auto-start` (step 5), not this skill.
- **Trend-sound presence** in the ranking → deferred with 5.4 trend-scan; sourcing ranks
  by mood only.
```

- [ ] **Step 2: Update `SKILLS/music-match/SKILL.md`** — replace the deferred-sourcing bullet

Find the "Not this skill" line:

```markdown
- **Sourcing** a track from the internet (royalty-free or otherwise) — deferred
  (B3); music-match ranks a **local folder** the user already has.
```

Replace with:

```markdown
- **Sourcing** a track from the internet (royalty-free or copyrighted) — that is the
  **music-source** skill (the `free`/`any` lanes); music-match ranks a **local folder**
  the user already has (`music.mode=local`).
```

- [ ] **Step 3: Wire `SKILLS/using-montage/SKILL.md` step 5**

Read the current step 5 (the music branch, added in the mood-match slice). It currently routes mood-but-no-track + a folder → music-match. Extend it so mood-but-no-track **without** a folder and `music_mode ∈ {free, any}` routes to **music-source**. Preserve the existing music-match branch. The resulting step 5 must read (adjust to match the file's exact surrounding wording):

```markdown
5. **Music** (if `SPEC.music == "auto"` and no track is locked):
   - `music_mode == local` **and** the user has a candidate folder → **music-match**
     (rank the folder by `SPEC.mood`).
   - `music_mode ∈ {free, any}` (no local folder) → **music-source** (source + rank
     from the internet; `any` is opt-in/copyright-gray — confirm with the user).
   - `SPEC.music` is an explicit track name → skip discovery; `music-source`
     `--track "<name>"` (or a local path) fetches it directly.
   Then `beats --auto-start` locks `MUSIC.json`.
```

- [ ] **Step 4: Verify**

Run: `ls SKILLS/music-source/SKILL.md && grep -c music-source SKILLS/using-montage/SKILL.md SKILLS/music-match/SKILL.md ; echo "EXIT: $?"`
Expected: the file exists; both SKILLs reference `music-source` (count ≥ 1 each).

- [ ] **Step 5: Commit**

```bash
git add SKILLS/music-source/SKILL.md SKILLS/music-match/SKILL.md SKILLS/using-montage/SKILL.md
git commit -m "docs: music-source SKILL + music-match cross-ref + using-montage wiring (5.5 sourcing)"
```

---

## Task 12: docs sync + final whole-slice review

**Files:**
- Modify: `docs/build-status.md`, `docs/pipeline-map.md`, `CLAUDE.md`,
  `docs/specs/2026-07-05-montage-skillset-design.md`,
  `docs/specs/2026-07-11-music-spine-design.md`,
  `docs/specs/2026-07-13-mood-match-design.md`

- [ ] **Step 1: `docs/build-status.md`** — add a Done entry and refresh Next-action

Add under the most-recent Done entry:

```markdown
- **music-sourcing (§5.5 B3, network lanes) DONE (2026-07-14)** — `scripts/lib/catalog.py`
  (Candidate + per-source discovery over urllib / yt-dlp) + `scripts/lib/fetch.py`
  (download + cache + sidecar + responsibility log) + `scripts/music_find.py` /
  `scripts/music_fetch.py` drivers reuse the mood engine to source & rank internet tracks:
  `free` = ccMixter (no key) / Jamendo (keyed upgrade), `any` = YouTube+iTunes+Deezer via
  yt-dlp (opt-in, `setup.sh --with-sourcing`). `music-source` SKILL. **5.5 now fully ✅.**
```

Update the "Next action" and the test-count line (run the suite in Step 5 for the exact number, e.g. "≈730 tests green").

- [ ] **Step 2: `docs/pipeline-map.md`** — flip 5.5 to ✅, bump the tally + date

- 5.5 row: append `+ sourcing (free/any, network) ✅`; change the 5.5 status marker from `◐` to `✅` and drop the "sourcing (B3)" blocker.
- Tally line: `11 ✅ · 3 ◐ · 2 ❌` → `12 ✅ · 2 ◐ · 2 ❌`.
- Bump `_Last updated: 2026-07-13._` → `_Last updated: 2026-07-14._`.

- [ ] **Step 3: `CLAUDE.md`** — two registry rows (after the mood-match rows)

```markdown
| Music-sourcing design | [2026-07-14-music-sourcing-design.md](docs/specs/2026-07-14-music-sourcing-design.md) | §5.5 network lanes (B3): `catalog.py` per-source discovery (Jamendo/ccMixter/YouTube/iTunes/Deezer) + `fetch.py` download/cache/sidecar; `music_find`/`music_fetch` reuse the mood engine; `free`=ccMixter-no-key/Jamendo-keyed, `any`=yt-dlp opt-in responsibility-switch; `music-source` SKILL. |
| Music-sourcing plan | [2026-07-14-music-sourcing.md](docs/plans/2026-07-14-music-sourcing.md) | Tasks 0–12: catalog contract/infra/searches/dispatcher/preview, fetch, both drivers, integration, `setup.sh --with-sourcing`, SKILL+wiring, docs. |
```

- [ ] **Step 4: cross-refs in the three specs**

- `docs/specs/2026-07-05-montage-skillset-design.md` §5.5 — add a "Built (2026-07-14, sourcing)" blockquote after the mood-match one (autonomous sourcing lands; the three lanes complete; `music-source` SKILL; `setup.sh --with-sourcing`).
- `docs/specs/2026-07-11-music-spine-design.md` §9 — change the "B3 — autonomous sourcing" bullet to note it **landed** 2026-07-14 (its own spec/plan), keeping only B4 pacing deferred.
- `docs/specs/2026-07-13-mood-match-design.md` §9 — change the "B3 autonomous sourcing" non-goal bullet to a "landed 2026-07-14 (cross-ref)" note.

- [ ] **Step 5: Run the full suite, then commit**

Run: `.venv/bin/python -m pytest -q ; echo "EXIT: $?"`
Expected: all green (unit sourcing tests + the rest); integration iTunes may `skip` off-network. Put the real passed-count into build-status.

```bash
git add docs/build-status.md docs/pipeline-map.md CLAUDE.md docs/specs/2026-07-05-montage-skillset-design.md docs/specs/2026-07-11-music-spine-design.md docs/specs/2026-07-13-mood-match-design.md
git commit -m "docs: sync build-status/pipeline-map/registry — 5.5 sourcing lands, 5.5 → ✅ (5.5 sourcing)"
```

- [ ] **Step 6: Final whole-slice review** — dispatch a fresh reviewer over the whole branch diff (`git diff main...feat/music-sourcing`) against `docs/specs/2026-07-14-music-sourcing-design.md`. Focus: the **rights invariant** (`free` never yt-dlp / never a youtube source; `any` always logs + records the license), the yt-dlp **module-invocation** boundary (venv-consistent, mocked in units), fail-loud remedies, and that no test hits the real network unmarked. Fix findings as **separate follow-up commits** (never `--amend`).

---

## Self-review (run after writing — completed)

**Spec coverage:** §1 scope → all tasks; §2 trigger/contract → Task 7/8 CLIs + SKILL (Task 11) read `Spec`/`music_mode`; §3 rights lanes → Tasks 3/4 (free ccMixter/Jamendo, any YouTube+catalog) + the rights invariant (Task 4/6); §4 discovery → Tasks 4/5/7; §5 fetch → Tasks 6/8; §6 dataflow → SKILL (Task 11); §7 wire-contracts → Tasks 0/6; §8 units → all; §9 deps/setup → Task 10; §10 fail-loud → Tasks 1/4/6 tests; §11 testing → every task + Task 9; §12 landmines → Task 4 (rights invariant), Task 6 (rights guard + responsibility log), Task 8 (driver stamps date); §13 non-goals → not built (trend-presence, Spotify, metadata-mood); §14 doc-sync → Task 12.

**Placeholder scan:** none — every code step carries complete code; every test step carries real assertions.

**Type consistency:** `Candidate(title, artist, source, ref, license, preview_url)` + `.slug()`/`.to_dict()`/`.from_dict()`; `SOURCES`; `has_ytdlp()`/`ytdlp_cmd()`/`http_download(url, dest)`/`_get_json`/`_free_source()`/`_jamendo_client_id()`; `search(mode, query, n, catalog=None)`; `preview_clip(candidate, cache_dir)`; `FetchedTrack(path, title, artist, source, source_url, license, date)` + `.sidecar()`; `fetch.download(candidate, mode, cache_dir, date)`; `music_find.build_shortlist(mode, mood_text, out_dir, *, n, query, cat)`; `music_fetch.fetch_pick/fetch_named` — all consistent across tasks.
