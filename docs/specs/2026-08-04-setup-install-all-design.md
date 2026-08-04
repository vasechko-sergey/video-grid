# Setup installs everything — no optional flags

**Design — 2026-08-04.** Backlog [#4](../fixes-backlog.md). `setup.sh` should
install the *whole* runtime, not a lean base plus opt-in extras behind flags. A
capability the pipeline is meant to have must be present after one `bash
setup.sh`, or the run silently degrades — which is exactly what happened: the
real montage run had no `demucs`, so its music in/out-point fell back to the
coarse librosa mix-silence proxy ("разбиение по фразам" — phrase-aware cut
points — was effectively off, unnoticed).

## The rule (from the user)

> Установка должна ставить всё, не должно быть опциональных флагов. Если для
> системы эта опция недоступна — пишешь об этом, но работать продолжаешь.

Install everything; no optional flags. If the platform genuinely cannot provide
a capability, **warn and continue** — never abort the venv, never leave the
capability silently missing without a printed reason.

## Current state (what the two remaining flags actually do)

- `--with-demucs` → `pip install demucs` (pulls torch). The one real optional
  *install* left. Absent → `choose_offset` uses the librosa mix-silence proxy.
- `--with-sourcing` → two things, **both now vestigial**:
  1. `pip install yt-dlp` — **redundant**: `yt-dlp` is already a baseline row in
     `requirements.txt`, so the guarded `pip show yt-dlp` always short-circuits.
  2. an interactive `read` prompt to paste/skip a Jamendo `client_id`.

`--with-fonts` and `--with-vidstab` were already folded into baseline earlier;
these two are the last opt-in flags.

## Decisions

### 1. `demucs` → baseline, warn-and-continue (NOT in `requirements.txt`)

Drop the `WANT_DEMUCS` gate; always attempt the install, guarded on
already-installed so a rerun is a clean no-op. Wrap the install so a failure
(e.g. no torch wheel for the platform) prints a warning naming the degradation
and continues:

```bash
"$VENV/bin/pip" show demucs >/dev/null 2>&1 || {
  echo "installing demucs (vocal separation for phrase-aware music points; pulls torch)..."
  "$VENV/bin/pip" install demucs \
    || echo "WARNING: demucs install failed (no torch wheel for this platform?) -> music in/out-point falls back to the librosa mix-silence proxy (coarser). Re-run 'bash setup.sh' to retry."; }
```

**Why not `requirements.txt`:** a row there installs under the same
`pip install -r` whose failure — under `set -euo pipefail` — aborts the entire
setup for every user on that platform (no venv, no recorded runtime root).
`demucs` is capability-not-requirement (the proxy fallback exists), so it must
degrade, not abort. Keeping it a separate `|| echo` step is the concrete shape
of the "warn and continue" rule. (The `|| echo` also makes the compound exit 0,
so `set -e` does not trip.)

### 2. `--with-sourcing` removed

- Delete the redundant `pip install yt-dlp` line — `yt-dlp` already ships via
  `requirements.txt`.
- The `any`-lane legal/responsibility gate is **untouched**: it lives in the
  sourcing *code* at use time, not at install time. Installing the `yt-dlp`
  binary does not invoke the `any` lane; nothing about the gate moves.
- Jamendo `client_id` → **non-blocking notice** (chosen over keeping the
  interactive `read`, which would block a non-interactive/CI setup, and over
  dropping it, which hides a real capability). Print once, only when no key is
  configured, then continue:

```bash
SRC_ENV="$SKILL_DIR/config/sourcing.env"
if [ -z "${JAMENDO_CLIENT_ID:-}" ] && ! grep -qs '^JAMENDO_CLIENT_ID=' "$SRC_ENV" 2>/dev/null; then
  echo "note: the free music lane uses ccMixter (no key). For Jamendo's richer CC"
  echo "  catalog, add 'JAMENDO_CLIENT_ID=...' to config/sourcing.env (https://devportal.jamendo.com/)."
fi
```

### 3. `--with-demucs` / `--with-sourcing` arg scan removed

The `for arg in "$@"` block and both `WANT_*` vars go. Unknown args were already
ignored by the `case`, so passing a now-stale flag stays harmless, but the
script no longer advertises or reads them.

### 4. `preflight.py`: `demucs` stays advisory, remedy updated

`demucs` can still be legitimately absent (warn-and-continue on a platform with
no torch wheel), and the pipeline still runs via the proxy — so the check stays
**advisory** (`required=False`), unchanged in kind. Only its remedy string moves
off the deleted flag: `bash setup.sh --with-demucs` → `bash setup.sh`. This has a
test (the remedy is asserted); update the test first (TDD).

## Non-goals / honest boundaries

- **Not** promoting `demucs` to a required preflight check — absence is a valid,
  handled degradation, not a failure.
- **Not** touching the `any`-lane responsibility gate, the ffmpeg-full /
  fonts / vidstab baseline blocks (already correct), or `requirements.txt`
  contents beyond noting `yt-dlp` is already there.
- **Not** adding cross-platform auto-install (the existing macOS/brew TODO
  stands); warn-and-continue already covers the "platform can't" case.
- `torch` also arrives here now (via `demucs`); the approved hero re-ID slice
  (#1) will reuse it. No coordination needed for this slice — noted only so the
  "demucs pulls torch, large" cost reads as shared, not wasted.

## Doc sweep

User-facing instructions lose the flags: `README.md`, `CLAUDE.md`,
`docs/development-workflow.md`, `docs/build-status.md`, and the
`skills/music-source` + `skills/using-montage` SKILLs. The authoritative
`docs/specs/2026-08-01-verify-runtime-design.md` row for `demucs` updates its
remedy. Historical design/plan docs that mention the flags as *past* context
(ffmpeg-baseline, plugin-packaging, start-offset, music-sourcing) are records of
their moment — left as-is, not rewritten.

## Verification

- `bash -n setup.sh` (syntax) — `setup.sh` is **not** run here (it installs; no
  autonomous system mutation).
- `pytest` full suite green (preflight remedy test updated).
- Update `docs/build-status.md` + backlog #4 in the same slice.
