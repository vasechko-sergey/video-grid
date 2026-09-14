# contact-sheet — router stage 4

(`<footage_root>` is the same raw-clips folder footage-intake scanned —
`FOOTAGE.json`'s `source` is a bare filename, not a path, so the build needs
the root to resolve it). Then **read every sheet it wrote** — `SHEETS.md`
links them. This is the only point in the conveyor where you see the raw
footage; every later stage works from your reading of it, so a skipped look
is a guess propagated through the whole reel. The sheets do not replace
`FOOTAGE.md` — the table carries the numbers, the sheets carry what the
numbers cannot say. Read both, and offer the sheets to the user at CP1
alongside the brief. **A run dir from before this stage existed** simply
needs the build run once — `next` reports `contact-sheet` forever until
`SHEETS.md` exists, even for a run already delivered and reviewed; running
the command above resolves it, it is not a sign anything is wrong.
