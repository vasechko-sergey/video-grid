# pacing — router stage 8

**pacing (§5.6, optional).** When `MUSIC.json` exists, invoke the **pacing**
skill — it **fits** the cuts `EDL.json` already holds onto the music's beat grid
(`"$VG" scripts.pacing --edl <run>/reels/<reel>/EDL.json --footage <run>/footage/FOOTAGE.json
--music <run>/reels/<reel>/MUSIC.json --out-dir <run>/reels/<reel>`) and writes `PACING.json` + `PACING.md`
into `<run>/reels/<reel>`. Then **apply the fit** by re-running edit-plan with the report:
`edit_plan build ... --pacing <run>/reels/<reel>/PACING.json [--spec <run>/reels/<reel>/SPEC.json]
--music <run>/reels/<reel>/MUSIC.json` — carry `--spec` through when reel-brief (step 5) ran,
same as step 6's first build. This second pass re-stamps `EDL.json` from scratch,
so a dropped `--spec` silently re-resolves the variety preset to `balanced` and
re-stamps that instead of the brief's mood. It also clears `EDL.brief_len`, which
turns the advisory `brief_length` check not-checked instead of comparing the
reel against the brief. `--music` here does a SECOND job
beyond feeding the beat grid: it fits the reel's *end* to a bar line
(`lib/outro.fit_outro`, applied after this pass binds every slot) so the music
resolves on a downbeat instead of stopping mid-phrase — read `EDL.md`'s **Music
outro** section for which rung won (`gap`/`no-gap`/`unchanged`, detailed in the
**edit-plan** skill's step 3). No `MUSIC.json` (a silent reel) -> skip this whole
step (named); the EDL stays pacing-less (`beat_slot` unset) and its length is
whatever the footage gives it. `montage status` never points `next` here (it is
optional).
