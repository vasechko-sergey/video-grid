# Plugin staleness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `verify_runtime` gains one blocking check that refuses a run whose
installed plugin version disagrees with the clone it is about to execute.

**Architecture:** The runtime contract grows a second layer. A pure
`preflight.plugin_staleness(records, clone_version)` decides four named states
from two plain inputs; an impure `verify_runtime._probe_plugin()` reads
`installed_plugins.json` and the clone's `plugin.json` and feeds it. The registry
row lands first in `CHECKS`, so a stale install is the first line of the report,
and `evaluate`'s existing keys-must-match invariant forces the probe and the row
to land together.

**Tech Stack:** Python 3, stdlib only (`json`, `os`, `pathlib`), pytest.

**Design:** [docs/specs/2026-09-25-plugin-staleness-design.md](../specs/2026-09-25-plugin-staleness-design.md)

## Global Constraints

- **Interpreter is `.venv/bin/python`.** Scripts run as modules (`pythonpath = .`
  in `pytest.ini`); never `cd scripts`.
- **Never run an installer.** No `bash setup.sh`, no `brew`, no `pip install`, no
  `claude plugin update`. This slice's whole subject is a read-only check; the
  remedy is PRINTED, never executed. The user runs it themselves (design §5).
- **Never run `git checkout --`, `git restore`, `git reset --hard`, or
  `git stash`.** To undo an edit to committed content use
  `git show HEAD:<path> > <path>`; when the file being mutated is **uncommitted**,
  save your own copy first (`cp <path> <path>.bak`). Run any mutation on an
  otherwise-clean tree and re-check `git diff --stat` after restoring.
- **Mutation batteries run under `PYTHONDONTWRITEBYTECODE=1`.** A one-byte edit
  can match the previous file's size and mtime-second and CPython then serves a
  stale `.pyc`.
- **`git add` named paths only**, never `git add -A`.
- **zsh does not word-split an unquoted variable.** A pytest selection held in a
  shell variable arrives as ONE argument and prints `no tests ran`, which reads
  exactly like a non-discriminating mutation row. Write selections literally.
- **Code, comments, commits and docs in English.**
- **`tests/integration/test_verify_runtime.py::test_real_runtime_is_ready` is
  EXPECTED RED from Task 2 onward on this machine** — the installed plugin is
  0.2.1 and the clone is not. This is the check working, and that test's own
  docstring sanctions it ("the suite is telling the truth about the machine, not
  about the code"). Do not skip it, do not exempt the key, do not weaken the
  assertion. Report every suite run as `N passed, M failed` with that test named
  as the expected failure. It is the ONLY test allowed to be red.

---

## File structure

| File | Responsibility |
|---|---|
| `scripts/lib/preflight.py` | **Modify.** One new `Check` row, first in `CHECKS`; the new pure `plugin_staleness`; the module docstring widened past "the setup.sh baseline contract". |
| `scripts/verify_runtime.py` | **Modify.** `import os`; the new `_probe_plugin` + its `_PROBES` entry; `_plugin_id()` deriving `<plugin>@<marketplace>` from the clone's two manifests. |
| `tests/lib/test_preflight.py` | **Modify.** The required-key-order pin gains `plugin`; new unit tests for all four `plugin_staleness` states. |
| `tests/lib/test_verify_runtime.py` | **Modify.** New `_probe_plugin` tests over `tmp_path`, plus the remedy-id pin. |
| `skills/verify-runtime/SKILL.md` | **Modify.** Description and body: the check exists, and its remedy is not `bash setup.sh`. |
| `CHANGELOG.md`, `.claude-plugin/plugin.json` | **Modify.** 0.14.0. |
| `CLAUDE.md`, `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md` | **Modify.** Registry rows, the closed row, the three §7 deferrals. |

---

## Task 1: The pure decision

**Files:**
- Modify: `scripts/lib/preflight.py`
- Test: `tests/lib/test_preflight.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `preflight.plugin_staleness(records, clone_version) -> tuple[bool, str]`
  where `records: tuple[tuple[str, str], ...] | None` is one `(scope, version)`
  pair per install record, or `None` when there is no install-record file at all.
  Task 2's probe is its only production caller.

This task adds NO registry row. `evaluate` raises when `CHECKS` and the raw probe
results disagree, so a `Check` without a probe would redden every `run()` test;
the row and the probe land together in Task 2. After this task the suite is
**fully green**.

- [ ] **Step 1: Write the failing tests**

Append to `tests/lib/test_preflight.py`:

```python
# --- plugin staleness (design 2026-09-25 §2.2). Four states, each named: the
# check must distinguish "there is no install to be stale" from "the install
# agrees" from "the install disagrees", because only the last is a defect and the
# first two are ordinary, legitimate configurations.

def test_no_record_file_passes_and_says_so():
    ok, detail = preflight.plugin_staleness(None, "0.14.0")
    assert ok is True
    assert "no install record" in detail


def test_record_without_this_plugin_passes_with_a_different_reason():
    """Distinct from None on purpose. Both mean 'nothing installed to be stale',
    but one means Claude Code has installed no plugins at all and the other means
    it has installed others and not this one. A single shared message would throw
    away a distinction the inputs carry."""
    ok, detail = preflight.plugin_staleness((), "0.14.0")
    assert ok is True
    assert "not installed as a plugin" in detail
    assert "no install record" not in detail


def test_matching_single_record_passes_and_names_the_version():
    ok, detail = preflight.plugin_staleness((("user", "0.14.0"),), "0.14.0")
    assert ok is True and "0.14.0" in detail


def test_a_behind_record_fails_and_names_both_versions():
    ok, detail = preflight.plugin_staleness((("user", "0.2.1"),), "0.14.0")
    assert ok is False
    assert "0.2.1" in detail and "0.14.0" in detail


def test_an_ahead_record_fails_too():
    """Direction is not interpreted (design §4) — a clone checked out behind its
    own install is still two things that disagree, and the one remedy fixes it
    either way because the marketplace IS the clone."""
    ok, _ = preflight.plugin_staleness((("user", "0.14.0"),), "0.2.1")
    assert ok is False


def test_every_mismatching_scope_is_named_not_only_the_first():
    """installed_plugins.json maps a plugin id to a LIST of records (user,
    project, local, managed). Reading only the first is the unvalidated-shapes
    defect: a reader defending itself with a guarantee the producer does not
    make."""
    ok, detail = preflight.plugin_staleness(
        (("user", "0.2.1"), ("project", "0.9.2")), "0.14.0")
    assert ok is False
    assert "user" in detail and "project" in detail
    assert "0.2.1" in detail and "0.9.2" in detail


def test_one_matching_record_does_not_excuse_a_mismatching_sibling():
    ok, detail = preflight.plugin_staleness(
        (("user", "0.14.0"), ("project", "0.2.1")), "0.14.0")
    assert ok is False
    assert "project" in detail
```

- [ ] **Step 2: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -k plugin -v`

Expected: 7 FAILED, each with
`AttributeError: module 'scripts.lib.preflight' has no attribute 'plugin_staleness'`.

- [ ] **Step 3: Implement**

Add to `scripts/lib/preflight.py`, after `evaluate`:

```python
def plugin_staleness(records: tuple[tuple[str, str], ...] | None,
                     clone_version: str) -> tuple[bool, str]:
    """Does the INSTALLED plugin agree with the clone about to run?

    `records` is one (scope, version) pair per install record, or None when there
    is no install-record file at all. The two absences are reported separately
    because they have different causes and the same conclusion: there is no
    installed instruction set that could be stale, so both PASS.

    A sequence — not one record — because installed_plugins.json maps a plugin id
    to a LIST (user / project / local / managed scopes). Every record is compared
    and every mismatch is named; `scope` is reported, never interpreted, since
    nothing here knows which one Claude Code actually loaded (design §6).

    The direction of a mismatch is deliberately not computed: the marketplace is
    the clone itself, so one remedy resolves it either way, and a number that
    changes no decision is not reported (design §4)."""
    if records is None:
        return True, "no install record — running from the clone"
    if not records:
        return True, "not installed as a plugin — running from the clone"
    bad = [(scope, ver) for scope, ver in records if ver != clone_version]
    if not bad:
        return True, f"{clone_version} installed"
    named = ", ".join(f"{scope} scope has {ver}" for scope, ver in bad)
    return False, (f"{named}; the clone is {clone_version} — the installed "
                   f"skills are not the ones this code expects")
```

- [ ] **Step 4: Run them and watch them pass**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py -v`

Expected: every test passes, the 7 new ones included.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: green — no registry row landed, so nothing else moved. Record the count.

- [ ] **Step 6: Commit**

```bash
git add scripts/lib/preflight.py tests/lib/test_preflight.py
git commit -m "feat(preflight): plugin_staleness — four named states for the installed-vs-clone question"
```

---

## Task 2: The registry row and the probe

**Files:**
- Modify: `scripts/lib/preflight.py` (the `CHECKS` tuple only)
- Modify: `scripts/verify_runtime.py`
- Test: `tests/lib/test_preflight.py`, `tests/lib/test_verify_runtime.py`

**Interfaces:**
- Consumes: `preflight.plugin_staleness(records, clone_version)` from Task 1.
- Produces: `verify_runtime._plugin_id() -> str` (`"<plugin>@<marketplace>"` read
  from the clone's `.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`)
  and `verify_runtime._probe_plugin() -> tuple[bool, str]`. Task 3's pin test
  calls `_plugin_id()`.

**The row and the probe MUST land in the same commit.** `evaluate` raises
`ValueError` when the raw keys and the registry keys differ, so a `Check` without
a `_PROBES` entry reddens every `run()` and CLI test in the suite.

**From this task on, `tests/integration/test_verify_runtime.py::test_real_runtime_is_ready`
is RED on this machine and that is correct** (Global Constraints, design §5).

- [ ] **Step 1: Write the failing registry test**

In `tests/lib/test_preflight.py`, change the existing
`test_registry_keys_unique_and_expected_split` required list — `plugin` goes
FIRST, matching the tuple order:

```python
def test_registry_keys_unique_and_expected_split():
    keys = [c.key for c in CHECKS]
    assert len(keys) == len(set(keys))
    assert [c.key for c in CHECKS if c.required] == [
        "plugin", "deps", "ffmpeg_bin", "drawtext", "vidstab", "font",
        "weights", "demucs"]
    assert [c.key for c in CHECKS if not c.required] == ["reid"]
```

And add, in the same file:

```python
def test_the_plugin_check_is_first_so_a_stale_install_is_the_first_line():
    """CHECKS's order is the report's order. The plugin question is outermost —
    'are you running the instructions you think you are?' — and cheapest (two
    file reads, no subprocess), so it leads."""
    assert CHECKS[0].key == "plugin"
```

- [ ] **Step 2: Write the failing probe tests**

Append to `tests/lib/test_verify_runtime.py`:

```python
def _install_record(tmp_path, entries):
    """Write a Claude Code installed_plugins.json carrying `entries` for this
    plugin, and point the probe's config dir at it."""
    import json as _json
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True, exist_ok=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(_json.dumps(
        {"version": 2, "plugins": {verify_runtime._plugin_id(): entries}}))
    return cfg


def _clone_manifest(tmp_path, version):
    """Give the probe a clone root whose plugin.json carries `version`.

    The fake marketplace is deliberately NOT named "video-grid": in the real
    manifests the plugin and the marketplace share a name, so a fixture that
    copied that could not tell which file each half of the id came from, and a
    probe reading `name` twice out of plugin.json would pass."""
    import json as _json
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True, exist_ok=True)
    (cp / "plugin.json").write_text(_json.dumps(
        {"name": "video-grid", "version": version}))
    (cp / "marketplace.json").write_text(_json.dumps({"name": "vg-market"}))
    return tmp_path / "clone"


def test_plugin_id_is_derived_from_the_two_manifests(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    assert verify_runtime._plugin_id() == "video-grid@vg-market"


def test_probe_plugin_passes_when_there_is_no_record_file(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "no install record" in detail


def test_probe_plugin_passes_on_a_matching_install(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user", "version": "9.9.9"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "9.9.9" in detail


def test_probe_plugin_fails_on_a_stale_install(monkeypatch, tmp_path):
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user", "version": "0.2.1"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "0.2.1" in detail and "9.9.9" in detail


def test_probe_plugin_passes_when_the_record_lists_other_plugins_only(
        monkeypatch, tmp_path):
    import json as _json
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    (cfg / "plugins" / "installed_plugins.json").write_text(_json.dumps(
        {"version": 2, "plugins": {"superpowers@elsewhere": [
            {"scope": "user", "version": "6.2.0"}]}}))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is True and "not installed as a plugin" in detail


def test_probe_plugin_defaults_to_the_home_config_dir(monkeypatch, tmp_path):
    """Without CLAUDE_CONFIG_DIR the record lives under ~/.claude. Path.home()
    honours HOME on posix, which is how this is reachable in a test at all."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    cfg = tmp_path / "home" / ".claude"
    (cfg / "plugins").mkdir(parents=True)
    import json as _json
    (cfg / "plugins" / "installed_plugins.json").write_text(_json.dumps(
        {"version": 2, "plugins": {verify_runtime._plugin_id(): [
            {"scope": "user", "version": "0.2.1"}]}}))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "0.2.1" in detail


@pytest.mark.parametrize("body,says", [
    ("{ not json", "Expecting"),                      # json's own parse message
    ('{"version": 2}', "plugins"),                    # the missing key, by name
    ('{"version": 2, "plugins": []}', "not a mapping"),
])
def test_an_unreadable_record_blocks_and_never_reads_as_fine(
        monkeypatch, tmp_path, body, says):
    """Cannot-answer is not allowed to read as 'nothing installed' — that is the
    silent-off this check exists to prevent — and it is not allowed to surface as
    a bare traceback either. It blocks, the detail names the path, and it names
    WHICH shape it could not read.

    That last assertion is what makes the three cases distinguishable: all three
    reach `ok is False`, two of them by a bare exception, so a test that only
    checked the boolean could not see the `isinstance` guard being deleted — a
    list with no `.get` raises anyway, just less legibly."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = tmp_path / "claude"
    (cfg / "plugins").mkdir(parents=True)
    rec = cfg / "plugins" / "installed_plugins.json"
    rec.write_text(body)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False
    assert str(rec) in detail
    assert says in detail
    assert "Traceback" not in detail


def test_a_record_entry_without_a_version_is_unreadable_not_skipped(
        monkeypatch, tmp_path):
    """Dropping it would turn a shape the reader does not understand into
    'nothing to compare', which passes."""
    monkeypatch.setattr(verify_runtime, "_ROOT", _clone_manifest(tmp_path, "9.9.9"))
    cfg = _install_record(tmp_path, [{"scope": "user"}])
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False
    # The KIND of failure is the assertion that discriminates. A lenient
    # projection (`e.get("version", "")`) also returns False — "" mismatches
    # every clone version — so it would report a STALE install where the truth is
    # a record shape the reader does not understand. Only the message separates
    # the two.
    assert "unreadable" in detail


def test_an_unreadable_clone_manifest_blocks_rather_than_raising(
        monkeypatch, tmp_path):
    """The clone is the tree the probe executes from and test_plugin_manifests.py
    gates its shape, so this is not an expected state — but it must not escape as
    a stack fragment through run()'s catch-all."""
    cp = tmp_path / "clone" / ".claude-plugin"
    cp.mkdir(parents=True)
    (cp / "plugin.json").write_text("{ not json")
    (cp / "marketplace.json").write_text('{"name": "video-grid"}')
    monkeypatch.setattr(verify_runtime, "_ROOT", tmp_path / "clone")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "empty"))
    ok, detail = verify_runtime._probe_plugin()
    assert ok is False and "Traceback" not in detail
```

- [ ] **Step 3: Run them and watch them fail**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py tests/lib/test_verify_runtime.py -v`

Expected, per test:

| test | failure |
|---|---|
| `test_registry_keys_unique_and_expected_split` | `AssertionError` — the list still starts at `"deps"` |
| `test_the_plugin_check_is_first_...` | `AssertionError: 'deps' == 'plugin'` |
| every `_probe_plugin` / `_plugin_id` test | `AttributeError: module 'scripts.verify_runtime' has no attribute '_plugin_id'` (collection of the parametrized case included) |
| `test_probes_keys_match_registry` | still PASSES — neither side has changed yet |

- [ ] **Step 4: Add the registry row**

In `scripts/lib/preflight.py`, make it the FIRST element of `CHECKS`:

```python
CHECKS: tuple[Check, ...] = (
    Check("plugin", "installed plugin matches the clone", True,
          "claude plugin update video-grid@video-grid"),
    Check("deps", "Python runtime deps import", True, "bash setup.sh"),
```

…the remaining seven rows unchanged.

- [ ] **Step 5: Add the probe**

In `scripts/verify_runtime.py`, add `import os` to the stdlib imports (alphabetical:
after `json`), then add before `_PROBES`:

```python
def _plugin_id() -> str:
    """`<plugin>@<marketplace>` — the key Claude Code files this install under.
    Derived from the clone's own two manifests rather than typed, so it cannot
    drift from them; the remedy string's copy is pinned to this by a test."""
    cp = _ROOT / ".claude-plugin"
    plugin = json.loads((cp / "plugin.json").read_text())["name"]
    market = json.loads((cp / "marketplace.json").read_text())["name"]
    return f"{plugin}@{market}"


def _probe_plugin() -> tuple[bool, str]:
    """Compare the INSTALLED plugin against the clone this code lives in.

    The two are installed by different tools into different directories: the
    skills come from Claude Code's version-keyed cache, the Python from the clone
    the recorded root names. Nothing compared them before (design §0.2).

    Read-only, and it reads the installer's own RECORD rather than the cache
    directory — the record is the installer's statement of what it did, and what
    this check asks is whether that statement agrees with the clone."""
    cfg = Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))
    record = cfg / "plugins" / "installed_plugins.json"
    try:
        clone_version = json.loads(
            (_ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    except Exception as e:
        return False, f"cannot read the clone's plugin.json in {_ROOT}: {e}"
    if not record.is_file():
        return True, "no install record — running from the clone"
    try:
        data = json.loads(record.read_text())
        plugins = data["plugins"]
        if not isinstance(plugins, dict):
            raise TypeError(f"'plugins' is {type(plugins).__name__}, not a mapping")
        entries = plugins.get(_plugin_id(), [])
        records = tuple((str(e["scope"]), str(e["version"])) for e in entries)
    except Exception as e:
        # Cannot-answer must not read as "nothing installed" — a blocking check
        # that can silently turn itself off is the failure it exists to prevent.
        return False, f"install record unreadable at {record}: {e}"
    return preflight.plugin_staleness(records, clone_version)
```

and register it FIRST in `_PROBES`, matching the registry order:

```python
_PROBES = {
    "plugin": _probe_plugin,
    "deps": _probe_deps,
```

- [ ] **Step 6: Run the unit tests**

Run: `.venv/bin/python -m pytest tests/lib/test_preflight.py tests/lib/test_verify_runtime.py -v`

Expected: all pass, including `test_probes_keys_match_registry`.

- [ ] **Step 7: Run the whole suite and confirm the ONE expected failure**

Run: `.venv/bin/python -m pytest -q`

Expected: exactly one failure —
`tests/integration/test_verify_runtime.py::test_real_runtime_is_ready` — whose
printed report's first line reads
`[FAIL] plugin: installed plugin matches the clone — user scope has 0.2.1; the clone is 0.13.0 …`.

Paste that first `[FAIL] plugin:` line into the task report. **If any OTHER test
fails, that is a real regression — stop and fix it.** If `test_real_runtime_is_ready`
*passes*, the probe is not reaching the real record: investigate, do not proceed.

- [ ] **Step 8: Commit**

```bash
git add scripts/lib/preflight.py scripts/verify_runtime.py tests/lib/test_preflight.py tests/lib/test_verify_runtime.py
git commit -m "feat(verify-runtime): block a run whose installed plugin disagrees with the clone"
```

---

## Task 3: The pinned id and the two widened descriptions

**Files:**
- Modify: `scripts/lib/preflight.py` (module docstring only)
- Modify: `skills/verify-runtime/SKILL.md`
- Test: `tests/lib/test_verify_runtime.py`

**Interfaces:**
- Consumes: `verify_runtime._plugin_id()` and the `Check("plugin", …)` row from
  Task 2.
- Produces: nothing new.

The id now appears twice — derived in the probe, literal in the remedy constant.
`Check.remedy` is a frozen field and widening that contract for one row costs more
than it saves (design §2.4), so the two spellings are machine-checked instead.

- [ ] **Step 1: Write the failing pin test**

Append to `tests/lib/test_verify_runtime.py`:

```python
def test_the_remedy_names_the_id_the_probe_actually_looks_up():
    """The plugin id lives in two places: derived from the manifests by
    _plugin_id(), and typed into the remedy a user is told to run. A remedy that
    updates a different id than the check reads would 'fix' nothing and the check
    would stay red with no way to clear it."""
    remedy = next(c.remedy for c in preflight.CHECKS if c.key == "plugin")
    assert remedy == f"claude plugin update {verify_runtime._plugin_id()}"
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/lib/test_verify_runtime.py::test_the_remedy_names_the_id_the_probe_actually_looks_up -v`

Expected: PASS on the first run — both sides already say `video-grid@video-grid`.
That is not the test being vacuous: its job is to hold them together from here on,
and Task 4's mutation battery proves it discriminates by changing one side.

- [ ] **Step 3: Widen the registry's own description**

`scripts/lib/preflight.py`'s module docstring opens by calling the registry "what
the `setup.sh` baseline contract is". Every row's remedy WAS `bash setup.sh`; one
now is not, and `setup.sh` does not install the plugin. Replace the first
paragraph with:

```python
"""Runtime-preflight registry (designs docs/specs/2026-08-01-verify-runtime-design.md
and docs/specs/2026-09-25-plugin-staleness-design.md).

The PURE half of the verify-runtime check: the CHECKS registry and how a set of raw
probe results becomes a RuntimeReport. No imports of the probed modules, no ffmpeg,
no filesystem — the impure probing lives in scripts/verify_runtime.py. That split is
what makes the report logic testable without a working install: feed evaluate()
fabricated results.

The registry covers TWO layers, not one. Seven rows are the `setup.sh` baseline
contract — what the installer put in the clone — and their remedy is `bash setup.sh`.
The `plugin` row is the other layer: whether the INSTALLED skills are the ones this
code expects, which `setup.sh` neither installs nor can fix. Its remedy is
`claude plugin update`. Leaving this docstring saying "the setup.sh baseline
contract" would be the inert, now-false comment this repo deletes rather than
qualifies.
"""
```

- [ ] **Step 4: Update the skill**

In `skills/verify-runtime/SKILL.md`:

**(a)** The `description:` gains the new check. It must keep the literal
`Tool index: references/tools.md.` (pinned by
`tests/test_skills_contract.py::test_every_skill_points_at_the_tool_index`) and
the literal role `step 0, before every stage` (pinned by
`test_every_skill_states_its_conveyor_place`). The whole value stays inside its
double quotes — an unquoted `": "` inside a YAML scalar is a parse error. Replace
the line with:

```yaml
description: "Preflight — verify the video-grid runtime is fully installed and print the exact command to fix any gap: the installed plugin matching this clone, deps, ffmpeg, drawtext and vidstab filters, font, YOLO weights, demucs. Read-only, never installs. Required — step 0, before every stage. Tool index: references/tools.md."
```

**(b)** In `## Overview`, replace `Assert the `setup.sh` **baseline contract** is
intact and print each gap's remedy.` with:

```markdown
Assert the runtime contract is intact and print each gap's remedy. Two layers: the
`setup.sh` **baseline** (deps, ffmpeg, filters, font, weights, demucs) and the
**installed plugin** — whether the skills Claude Code loaded are the ones this
clone's code expects. Read-only: it names what to run, it never runs an installer.
Designs: `docs/specs/2026-08-01-verify-runtime-design.md`,
`docs/specs/2026-09-25-plugin-staleness-design.md`.
```

**(c)** In `## The Process` step 3, after the bullet beginning
`- **Exit non-zero:**`, add a nested bullet:

```markdown
   - A failing **`plugin`** check is the one gap whose remedy is not `bash setup.sh`:
     the clone's code and the installed skills disagree about which version is
     running. Relay `claude plugin update …` verbatim as above, and add that Claude
     Code must be **restarted** afterwards — the update rewrites the cache, it does
     not reload the skills this session already has in context.
```

**(d)** In `## Boundaries`, after the `**Read-only.**` bullet, add:

```markdown
- **Reports a version disagreement, never that the instructions are right.** A
  matching install of a skill set with a wrong sentence in it passes, and a clone
  edited without a version bump is invisible by design — the version is the
  install key.
```

- [ ] **Step 5: Run the skill and CLI contract tests**

Run: `.venv/bin/python -m pytest tests/test_skills_contract.py tests/test_skill_convention.py tests/test_verify_runtime_skill.py tests/test_cli_help.py -q`

Expected: green. If the description test fails, the `Tool index:` pointer or the
`step 0, before every stage` role was dropped from the line.

- [ ] **Step 6: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: the same single expected failure as Task 2 and nothing else.

- [ ] **Step 7: Commit**

```bash
git add scripts/lib/preflight.py skills/verify-runtime/SKILL.md tests/lib/test_verify_runtime.py
git commit -m "feat(verify-runtime): pin the remedy's plugin id, and say the registry covers two layers"
```

---

## Task 4: The mutation battery, the version bump, the docs

**Files:**
- Modify: `CHANGELOG.md`, `.claude-plugin/plugin.json`, `CLAUDE.md`,
  `docs/backlog.md`, `docs/backlog-closed.md`, `docs/build-status.md`
- Test: whichever files the battery's GREEN rows force

**Interfaces:**
- Consumes: everything from Tasks 1–3.
- Produces: nothing in code.

### Step 1: Run the mutation battery

**Run every row under `PYTHONDONTWRITEBYTECODE=1`.** For each row: apply the
mutation, run the named selection **written out literally** (a selection in a
shell variable arrives as one argument and prints `no tests ran`, which looks
exactly like a non-discriminating row), record RED or GREEN, then restore with
`git show HEAD:<path> > <path>` and re-check `git diff --stat` is empty before the
next row.

`tests/integration/test_verify_runtime.py::test_real_runtime_is_ready` is red
throughout and is not evidence for any row — **exclude it from every selection**,
and never use a bare `pytest -q` as a row's discriminator.

| # | Mutation | Selection | Expect |
|---|---|---|---|
| 1 | `preflight.plugin_staleness`: `if records is None:` → `if not records:` (collapsing the two absences into one) | `tests/lib/test_preflight.py` | RED |
| 2 | `plugin_staleness`: drop the `if not records:` arm so `()` falls through to the comparison | `tests/lib/test_preflight.py` | RED |
| 3 | `plugin_staleness`: `bad = [...]` → `bad = [records[0]] if records[0][1] != clone_version else []` (first record only) | `tests/lib/test_preflight.py` | RED |
| 4 | `plugin_staleness`: the mismatch message drops `{scope}` | `tests/lib/test_preflight.py` | RED |
| 5 | `plugin_staleness`: the mismatch message drops `the clone is {clone_version}` | `tests/lib/test_preflight.py` | RED |
| 6 | `plugin_staleness`: `ver != clone_version` → `ver > clone_version` (only "ahead" fails) | `tests/lib/test_preflight.py` | RED |
| 7 | `CHECKS`: move the `plugin` row from first to last | `tests/lib/test_preflight.py` | RED |
| 8 | `CHECKS`: the `plugin` row's `required` `True` → `False` | `tests/lib/test_preflight.py` | RED |
| 9 | `CHECKS`: the `plugin` row's remedy id → `video-grid@marketplace` | `tests/lib/test_verify_runtime.py` | RED |
| 10 | `_plugin_id`: `marketplace.json` → `plugin.json` for the market half | `tests/lib/test_verify_runtime.py` | RED — **only because `_clone_manifest` names the fake marketplace `vg-market`.** The real manifests name the plugin and the marketplace both `video-grid`, so a fixture copying that would make this mutation invisible. |
| 11 | `_probe_plugin`: the `except` around the record read returns `(True, "…")` instead of `(False, …)` | `tests/lib/test_verify_runtime.py` | RED |
| 12 | `_probe_plugin`: drop the `isinstance(plugins, dict)` guard | `tests/lib/test_verify_runtime.py` | RED — **on the MESSAGE, not the boolean.** A list has no `.get`, so the case still ends `ok is False` by AttributeError; what the guard buys is `'plugins' is list, not a mapping` instead of `'list' object has no attribute 'get'`, and the parametrized `says` assertion is the only thing holding it. |
| 13 | `_probe_plugin`: `entries` projection uses `e.get("version", "")` instead of `e["version"]` | `tests/lib/test_verify_runtime.py` | RED — **on `"unreadable" in detail`, not on `ok`.** `""` mismatches every clone version, so the lenient projection also fails the check; it just calls a shape it cannot read a STALE install. The boolean cannot see it. |
| 14 | `_probe_plugin`: `if not record.is_file():` → `if not record.exists():` | `tests/lib/test_verify_runtime.py` | **GREEN expected** — no test builds a *directory* at that path, and none is planned: the two predicates differ only there. Do not close this with a new test unless you judge the case reachable; record the non-discrimination and why (this is the same shape as `Path("")` being truthy, which the retry-record slice DID close — the difference is that an empty string reaches `Path` from a contract field, while a directory named `installed_plugins.json` reaches it from nowhere). |
| 15 | `_probe_plugin`: `os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude")` → `Path.home() / ".claude"` (ignore the env var) | `tests/lib/test_verify_runtime.py` | RED |
| 16 | `_probe_plugin`: the same expression → `os.environ["CLAUDE_CONFIG_DIR"]` (no default) | `tests/lib/test_verify_runtime.py` | RED |
| 17 | `_PROBES`: delete the `"plugin"` entry | `tests/lib/test_verify_runtime.py` | RED |
| 18 | `skills/verify-runtime/SKILL.md`: drop `Tool index: references/tools.md.` from the description | `tests/test_skills_contract.py` | RED |

Every GREEN that is not row 14 is a coverage hole: close it with a new test that
is confirmed red under the mutation and green without it, and say so in the report.

- [ ] **Step 2: Record the battery result** in the task report — the roll-call,
  and for every row you closed, the test you added.

- [ ] **Step 3: Bump the version**

`.claude-plugin/plugin.json`: `"version": "0.13.0"` → `"version": "0.14.0"`.

MINOR, not PATCH: a new blocking runtime check is a behaviour change for anyone
installing it — the same call the 0.12.0 chroma slice made for a new advisory
check.

Add to the top of `CHANGELOG.md`, immediately under the intro paragraphs (the
heading format is pinned by
`tests/test_plugin_manifests.py::test_every_changelog_heading_is_a_semver_and_they_descend`
as `## X.Y.Z — YYYY-MM-DD`):

```markdown
## 0.14.0 — 2026-09-25

- `verify_runtime` now refuses a run whose **installed plugin disagrees with the
  clone it is about to execute**. The code and the instructions come from two
  different places — the Python from the clone the recorded root names, the skills
  from Claude Code's version-keyed cache — and nothing compared them. Measured on
  the machine this shipped from: the cache held 0.2.1 against a clone at 0.13.0,
  392 commits, all fourteen skill bodies and all fourteen always-resident
  descriptions stale, and a *required* conveyor stage (`episodes-geometry`, the
  seam `match-grade` measures the shipped crop in) mentioned nowhere in the
  instructions the agent actually reads.
- The remedy is `claude plugin update video-grid@video-grid`, printed like every
  other gap. **Restart Claude Code afterwards** — the update rewrites the cache,
  it does not reload the skills a running session already holds.
- Not installed as a plugin? Nothing changes: a missing install record reads as
  "running from the clone" and passes.
```

- [ ] **Step 4: Sync the docs**

**`CLAUDE.md`** — add two rows to the Quick Reference table, immediately after the
`Verify-runtime plan` row, matching the existing two-row design/plan idiom:

```markdown
| Plugin staleness design | [2026-09-25-plugin-staleness-design.md](docs/specs/2026-09-25-plugin-staleness-design.md) | The runtime contract's second layer: the code comes from the clone (`bin/vg` via the recorded root) and the instructions from Claude Code's version-keyed cache, and nothing compared them. **§0 is the measurement half and it re-frames the row**: the cache is the live load path (six PID locks, not inference), so what is stale is the INSTRUCTIONS, not the code — 14 of 14 skill bodies and 14 of 14 always-resident descriptions, zero identical; `geometry` appears **0 times** in the installed router against 7 in the clone's, so the required `episodes-geometry` stage cannot be invoked at all; and `reels/` occurs **101 times** in the clone's skills and **0** in the installed ones. **§0.6 overturns the obvious instrument**: a repo-wide flag sweep finds exactly ONE dead flag, because `--edl`/`--footage-root` survive on other commands while being gone from `match_grade`, whose installed invocation the live CLI refuses. **§0.7 is why the row is closable**: the stale `verify-runtime` skill still resolves `$ROOT` and runs the clone's code, so a new `Check` reaches a real run with no reinstall. §4 rejects reporting the direction (the marketplace IS the clone, so one remedy serves both). §5: the slice's acceptance is the USER running the remedy — `test_real_runtime_is_ready` is red until they do, exactly as its own docstring prescribes. |
| Plugin staleness plan | [2026-09-25-plugin-staleness.md](docs/plans/2026-09-25-plugin-staleness.md) | Tasks 1–4: the pure four-state `preflight.plugin_staleness`, the `CHECKS` row landing first together with `verify_runtime._probe_plugin` (they must share a commit — `evaluate` raises on a row without a probe), the machine-checked remedy id and the two now-false descriptions, and an 18-row mutation battery whose row 14 is an expected GREEN with its reason written out. |
```

Also update the archive-count parenthetical in the **Backlog archive** row: 69 → 70.

**`docs/backlog.md`** — delete the row beginning `**Nothing detects that the
installed plugin is behind the repo.**` from P2, and add three bullets to P3's
`**Packaging / runtime**` group, each ending with ` ·` except the group's last:

```markdown
nothing gates that a run's instructions match its code at the CONTENT level —
0.14.0's check reports a version disagreement, and the fourteen stale bodies it
found are counted, not repaired; a content gate needs an answer to the cry-wolf
problem first (the version is the install key precisely because this repo bumps
once per slice) (plugin-staleness §7) ·
nothing verifies the recorded root is a checkout of the marketplace it claims —
`~/.config/video-grid/root` and `known_marketplaces.json`'s `installLocation` both
name a directory and are never compared, so a `setup.sh` run from a second clone
would point the skills at one tree while the plugin was installed from another,
and every check would still pass (plugin-staleness §7) ·
the `gitCommitSha` the installer records is unused — it resolves in the clone and
yields an exact commit distance (392 on the machine 0.14.0 shipped from), strictly
sharper than the version and strictly noisier, since any docs commit moves it
(plugin-staleness §7)
```

**`docs/backlog-closed.md`** — add the closed row under *Closed from P2* with its
closure note: the row asked for detection of a version gap and got it, but its
premise needed correcting — nothing was behind *except the instructions*, the code
was always the clone's, and the sharpest consequence (a required stage absent from
the router) was not in the row.

**`docs/build-status.md`** — add the Done entry: the four tasks, the battery
roll-call, and the fact that the slice's acceptance is an action only the user can
take.

- [ ] **Step 5: Run the whole suite**

Run: `.venv/bin/python -m pytest -q`

Expected: the single expected failure and nothing else. Report the exact counts.

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json CHANGELOG.md CLAUDE.md docs/backlog.md docs/backlog-closed.md docs/build-status.md
git commit -m "docs: close the plugin-staleness row, file three deferrals, bump to 0.14.0"
```

---

## Self-review

**Spec coverage.** §2.1 row → Task 2 Step 4. §2.2 pure function and its four
states → Task 1. §2.3 probe, config dir, unreadable handling → Task 2 Steps 5 and
2. §2.4 derived id + pin → Task 2 Step 5 and Task 3 Step 1. §2.5 docstring → Task
3 Step 3. §3's "the installed skill needs no edit" is a fact, not work. §4's
rejection is enforced by battery row 6 and Task 1's `test_an_ahead_record_fails_too`.
§5 is the Global Constraints' expected-red rule plus Task 4's honest counts. §6 is
carried into the skill's Boundaries (Task 3 Step 4d) and the changelog. §7 → Task 4
Step 4's three P3 bullets.

**Placeholder scan.** No TBD/TODO; every code step carries its literal text; the
battery's expected-GREEN row states its reason rather than deferring judgement.

**Type consistency.** `plugin_staleness(records, clone_version) -> tuple[bool, str]`
is used with exactly that signature in Task 1's tests, Task 2's probe, and the
battery. `_plugin_id() -> str` is defined in Task 2 Step 5 and consumed in Task 2's
test helpers and Task 3's pin. The registry key is `"plugin"` in all four tasks.

**Three plan defects found by running the battery's own predictions against the
planned tests' reachable inputs, before any code existed.** Each was a row
predicted RED whose named test could not see the mutation, and each is fixed in
the test rather than downgraded in the table: row 10 (both real manifests say
`video-grid`, so the fixture now names the fake marketplace `vg-market`), row 12
(a list raises anyway — the guard buys a message, so the message is pinned), and
row 13 (`""` mismatches every version, so the lenient projection also returns
False — the assertion moved onto the failure's KIND). This is the memory rule's
second half: a run assertion needs reachable inputs, and `ok is False` was
reachable two different ways.

**One correction folded in from writing the plan.** The design's §2.3 said an
unreadable record is blocking but did not say what makes a record unreadable. The
plan fixes the predicate: the file must parse as JSON, carry a `plugins` **mapping**,
and every entry for this id must carry `scope` and `version`. A `plugins` key that
is absent or is not a mapping is unreadable — *not* "this plugin is not installed" —
because a blocking check that can silently turn itself off on a producer-side shape
change is the failure it exists to prevent. Deliberately NOT read: the file's own
`"version": 2` schema marker. No schema 3 exists, and a policy invented against an
unseen shape would be speculation; the `plugins`-mapping requirement already stops
the silent-off without one.
