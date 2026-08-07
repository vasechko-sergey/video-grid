# Editorial-constraint memory — design (2026-08-07)

Backlog **#14** (`docs/fixes-backlog.md`), the last cheap item of the
cinematic-quality playbook's priority 3 (`docs/cinematic-quality-playbook.md`
§4). A user-stated editorial rule must persist across iterations and bind every
re-cut, instead of living in a chat message that the next render forgets.

## 0. Where this comes from

The 2026-08-03 real run broke two rules the user had stated out loud:

> «про обе сцены с дроном я тебе называл героев — и ты все равно нарушил
> правило что один открывает второй закрывает»

> «я давал образец и сказал чтобы эпизоды не повторялись — а тут минимум два
> повтора»

Both are *mechanically checkable over an EDL*. Neither was checked, because
neither was written anywhere a checker could reach. That is the whole defect:
not judgement, not taste — **the rule had no home on disk**.

Nothing about the two rules needed a model, a new sensor, or a re-scan. They
needed a file and a gate.

## 1. What must be true

1. A stated rule survives the conversation that stated it.
2. Every re-cut is judged against it — not the first one only.
3. A violated rule stops the cut *before* `EDL.json` lands, with a remedy.
4. Nothing is stored that the machine does not actually check. A file that
   remembers a rule but cannot enforce it is worse than no file: it converts
   "forgotten" into "believed handled".

(4) is why the vocabulary is closed and an unknown rule kind is a **load-time
refusal**, not a stored note. The cost is stated honestly in §10.

## 2. The unit of identity: the shot

An episode is identified by the pair `(source, shot)`, where the shot is the
scene-cut segment of the source clip that the episode's in-point falls into.

This unit already exists and is already authoritative: `FootageClip.scene_cuts`
holds the cuts, `FootageClip.room_after` measures the room to the next one, and
both `edit_plan.window_to_episode` and `edit_plan._merge_windows` already refuse
an episode whose span crosses a cut. So **every episode lies inside exactly one
shot, by construction** — the identity is total, with no episode left
unclassifiable.

`no_repeat` and `exclude` both key on this unit. The consequence is deliberate:
two episodes carved from *the same drone pass* are a repeat even when their
time spans do not overlap. The narrower reading (refuse only overlapping
intervals) would catch a literal duplicate and miss exactly the case the run
produced. A window index is the wrong unit for the same reason —
`carve.units_for_span` deliberately emits overlapping candidate windows, so two
different indices routinely name the same moment.

`FootageClip` gains one method for this, beside `room_after`, so the geometry
keeps a single authority:

```python
def shot_at(self, t: float) -> tuple[float, float]:
    """The [start, end) of the uninterrupted shot containing `t`."""
```

## 3. The file and the vocabulary

`CONSTRAINTS.json`, beside `project.json`:

```json
{"rules": [
  {"kind": "no_repeat", "stated": "эпизоды не должны повторяться"},
  {"kind": "open_with", "hero": "Serge", "stated": "дрон-сцена с Сержем открывает"},
  {"kind": "close_with", "hero": "Anna", "stated": "вторая дрон-сцена закрывает"},
  {"kind": "exclude", "source": "clips/DJI_0042.MP4", "window": 7,
   "stated": "этот дубль не брать"}
]}
```

Four kinds, and only four:

| kind | fields | binds |
|------|--------|-------|
| `no_repeat` | — | no two episodes share one `(source, shot)` |
| `open_with` | `hero` | episode 0 pins that cast name |
| `close_with` | `hero` | the last episode pins that cast name |
| `exclude` | `source`, `window` (optional) | no episode inside that shot (or that clip) |

`stated` is **required and non-empty on every rule**: the user's own words. It
is what a refusal quotes back, and it is the only thing separating a rule the
user gave from a rule the agent invented for itself.

The loader refuses, loudly, with the supported vocabulary in the message:

- an unknown `kind`;
- a field that does not belong to the kind (a typo'd `heroes` must not silently
  disable a bookend);
- a missing required field, or a blank `stated`;
- a **second** `no_repeat`, `open_with`, or `close_with` — these are singletons,
  and two `open_with` rules naming different heroes is a contradiction that can
  never be satisfied. Refusing at load beats refusing every cut forever;
- a duplicate `exclude` (same source and window). `exclude` is otherwise
  repeatable — several takes may be banned.

Who writes it: the agent, with `Write`, the way it already authors
`selection.json`. There is no `constraints add` driver — validation at load is
strict, so a malformed file fails the build loudly rather than passing a
half-understood rule. The skills carry the instruction to capture a rule the
moment the user states one.

## 4. The module

New pure `scripts/lib/constraints.py` — stdlib only, no IO beyond `from_json`,
the shape of `spec.py` and `moodpreset.py`:

```python
@dataclass
class Rule:          # kind + its fields + `stated`; per-kind validation
@dataclass
class Constraints:   # the rule list; from_dict/from_json/to_dict; cross-rule refusals
@dataclass
class Placed:        # one episode reduced to what a rule can judge
    source: str
    shot: tuple[float, float]
    hero: str | None
@dataclass
class Violation:     # rule_index, kind, stated, message
@dataclass
class ConstraintReport:   # rules echoed + violations; `.ok`; to_dict/from_dict

def evaluate(rules: Constraints, placed: tuple[Placed, ...],
             footage: Footage) -> ConstraintReport
```

`evaluate` judges a **projection**, not `EDLEpisode` objects. That is not
fastidiousness: `edl.py` must import the report type to carry it (§8), so a
`constraints.py` that imported `edl.py` would close an import cycle. The same
boundary `moodpreset.VarietyReport` already draws — it counts shot sizes handed
to it and never imports the EDL either. `Footage` is safe to take whole and is
taken whole: `footage.py` imports neither `edl` nor `constraints`, and
`exclude` needs the clip's scene cuts to resolve `window` → shot (§7), so the
rule's semantics stay in one module instead of half-resolving in the caller.

The projection lives in `edit_plan`, which holds both halves (the clip, for
`shot_at`, and the episode, for the hero pin). Two details it owns:

- `hero` reaches `Placed` only when it is a **cast name** — a `str` that is not
  in `models.HERO_RULES`. A bbox tuple, a track id, or the rule string
  `"largest"` all project to `None`, which a bookend rule reads as
  *unsatisfied*, never as *satisfied*.
- The shot comes from `clip.shot_at(episode_start)`, so the rule and the
  `room_after` refusal agree on where a shot ends.

## 5. The gate

The same split the variety gate uses, for the same reason: **`build_edl`
measures, `write_edit_plan` refuses.**

- `build_edl(..., constraints: Constraints | None = None)` — keyword-only,
  beside `aspect`/`preset`. Evaluates after the episodes are final (pacing
  binding changes `dur`, which none of the four rules read) and attaches the
  report to the EDL. It never refuses: a caller building an EDL in memory still
  gets the finding.
- `write_edit_plan` returns
  `{"status": "stop_and_report", "finding": {"reason": "constraint-violation", …}}`
  and writes nothing. A distinct reason from `variety-gap` and `edl-invalid`,
  so the three failure classes stay attributable without parsing prose.

**No waiver.** The variety gate's waiver is legitimate because the rule there is
the machine's guess (a mood preset) and a human may overrule a guess. Here the
rule is the user's own sentence; an agent that could waive it would reproduce
exactly the 2026-08-03 failure with a paper trail. The only way past a violated
rule is the user editing or deleting it in `CONSTRAINTS.json`.

**Order: constraints before variety.** A human's stated rule outranks a preset's
inference, so its finding is the one the caller sees first.

## 6. Discovery — and why that IS the memory

`write_edit_plan` derives the path from the already-required `--project`:

```python
Path(project_path).parent / "CONSTRAINTS.json"
```

There is no `--constraints` flag to forget. A missing file means no rules:
`EDL.constraints` stays `None`, which reads as *not evaluated*, never as
*passed*. A present file is enforced on every invocation.

That is the whole memory mechanism. `edit_plan build` is re-run for every
re-cut — and twice per cut once pacing is involved, since the fitter reads the
EDL and the plan is rebuilt with `--pacing` — so the rules bind each iteration
by construction rather than by anyone remembering to pass them.

## 7. The four checks

**`no_repeat`** — group the placed episodes by `(source, shot)`; any group of
two or more is a violation. The message names both episode indices and the
shot's time span, so the fix is mechanical: *"episodes 2 and 7 are both from
clips/DJI_0042.MP4 [12.4s–31.8s] — one shot, two episodes."*

**`open_with` / `close_with`** — `placed[0].hero` (resp. `placed[-1].hero`) must
equal the rule's name. Three ways to fail, all violations with their own
remedy: the wrong hero is pinned; nothing is pinned; or the pin is a bbox, a
track id, or a `HERO_RULES` string, which names a *tracking target*, not a
person. The last case is the one worth stating explicitly — an unpinnable
episode cannot satisfy a bookend rule, and treating "cannot tell" as "fine"
would rebuild the silent pass this slice exists to remove. Both checks assume
at least one episode, which `build_edl` already guarantees by refusing an empty
selection; on a one-episode cut the single episode is judged by both rules, so
an `open_with`/`close_with` pair naming different heroes correctly refuses it.

**`exclude`** — with `window`, the banned region is the shot containing that
window's start (the same unit as `no_repeat`); without it, the whole clip. Any
episode inside it is a violation. An out-of-range `window` or a `source` absent
from FOOTAGE is refused when the rule is evaluated, naming the clip list — a
stale rule pointing at footage that no longer exists must not quietly enforce
nothing.

## 8. The record

`EDL.constraints: ConstraintReport | None`, round-tripped in `EDL.json` and
rendered as a section of `EDL.md` — the rules that were checked, quoted in the
user's words, and the fact that they passed. The artifact then carries its own
evidence, the way `EDL.variety` already does, and a later reader can see which
rules bound the cut without reconstructing the session.

## 9. Validation

Pure logic and file plumbing — no ffmpeg, no new fixture bytes.

- **Contract:** each kind's happy path and each refusal (unknown kind, foreign
  field, missing field, blank `stated`, singleton duplicate, duplicate
  `exclude`), plus `to_dict`/`from_dict` round-trips.
- **Projection:** `shot_at` at a boundary (a `t` exactly on a cut belongs to the
  later shot, matching `room_after`'s `c > start` rule), and the
  cast-name-vs-`HERO_RULES` discrimination.
- **Checks:** one violating and one clean case per kind, asserting the whole
  `ConstraintReport`, not just `.ok`.
- **Gate, through `write_edit_plan` on tmp dirs:** file absent → written,
  `constraints` is `None`; file present and clean → written, the report is in
  `EDL.json`; file present and violated → `stop_and_report` with
  `reason == "constraint-violation"` and **no EDL.json on disk**; violated
  constraint *and* a variety gap → the constraint is the reported one.
- **Integration:** the existing SP3→SP1 fixture gains a `CONSTRAINTS.json`, so
  the discovery-by-convention path is proven end-to-end rather than only in
  unit tests.

## 10. Honest limits

- **The vocabulary is four kinds.** A rule outside them cannot be written down
  at all — it stays in chat and is forgotten, exactly as today, for that class.
  This is the accepted cost of §1.4, and it is only honest while the vocabulary
  grows as real rules appear. "Not expressible" must reach the user as a
  sentence, not as silence: the skills instruct the agent to say so when a
  stated rule has no kind.
- **`edl_to_reel` never sees this gate.** A hand-authored `EDL.json` is the SP1
  front door by design (extract-spine design §2); it bypasses `edit_plan`
  entirely, and with it every rule here.
- **Deleting `CONSTRAINTS.json` passes everything.** The invariant is *no
  silent bypass*, not *no bypass* — the same boundary the attested-run design
  §11 draws. An agent with a shell can always delete a file; what it cannot do
  is skip the gate while the file is there.
- **`no_repeat` catches one shot twice, not two shots that look alike.** Two
  separate passes of the same beach, cut identically, read as different shots.
  Visual similarity is a different sensor (intake's phash is per-window and
  never reaches the EDL); deferred, §11.
- **A bookend rule binds only where the EDL can express it.** It requires cast
  names on the episodes, so a run without `cast.json` can satisfy the rule only
  by failing loud. That is the intended direction of failure, but it does mean
  the rule is unusable — not merely unchecked — on an un-cast project.
- **The gate proves the rules were checked, never that the reel is good.** It
  is the same shape as the contact-sheet stage's §9: presence of the check, not
  proof of judgement.

## 11. Deferred

- **More kinds, as real rules appear** — `no_adjacent` (two drone shots must not
  touch), `require` (this clip must appear), `max_uses` (a hero at most N
  times), `order` (A before B). None has been stated by a user yet, and
  guessing a rule's shape before someone needs it is how a vocabulary acquires
  fields nothing sets.
- **Visual-similarity repeats** — two different shots that read as the same
  moment. Needs a per-episode perceptual measure at EDL level.
- **Surfacing the active rules in `montage status`**, so a human sees them at
  the checkpoints without opening the file.
- **Carrying the rules through `edl_to_reel`'s hand-authored front door**, the
  §10 hole. It would need the rules to reach a stage that has no FOOTAGE in
  hand, so the shot unit would have to be re-derived — its own slice.
