# Tabulator Migration Plan

Goal: replace the hand-rolled review table in `app/static/cn4m.js` with [Tabulator](https://tabulator.info/) (MIT, zero-dep, vendored like jQuery/Bootstrap), unlocking header filters, proper multi-column sorting, range selection, and export — without touching the Flask/Celery backend.

**Safety net:** before starting, tag the current state so revert is one command:
```
git tag pre-tabulator && git push origin pre-tabulator
```

---

## The standard smoke test (run between every phase)

Referred to below as **FULL CYCLE**:

1. `docker compose up -d`, open http://localhost:5000, hard-refresh (Cmd+Shift+R).
2. Drop a mix of files into `repo/`: a conforming video, a video with wrong codec, one with wrong resolution, one with wrong fps, an audio file, an image.
3. **START** → table renders; row count matches files dropped; flags panel shows any invalid files.
4. QC highlights: bad codec / width / height / fps cells are red with correct "Expected:" tooltips; conforming rows clean.
5. Icons: file-type icon on Name; version-up vs new-file icon on Version.
6. Sort 2–3 columns asc/desc (include Size and a numeric column).
7. Header checkbox selects/deselects all; SELECT ALL AUDIO / DE-SELECT ALL AUDIO only affect audio rows.
8. Select one row → APPROVE; another → QUARANTINE; rows disappear; files actually move; progress messages appear.
9. Select a video + preset → TRANSCODE; verify output file and progress text.
10. UPDATE GOOGLE SHEET → approved assets land in the sheet.
11. Browser console: zero errors throughout.

---

## Phase 0 — Baseline capture

- [x] `git tag pre-tabulator` — created locally at `d302155` (annotated). **Not yet pushed** — run `git push origin pre-tabulator` when ready.
- [ ] Screenshot the current table (normal + a QC-failure row) for visual comparison during the theme pass.
- [x] **Known bugs verified against `app/helpers.py` — expect the migration to *fix* these, don't preserve them:**

  | # | Bug | Cause | Severity |
  |---|-----|-------|----------|
  | 1 | **Duration sort does nothing** | `helpers.py:552` stores `track.other_duration[4]` — a timecode string like `00:01:30:00`. The header declares `data-type="number"`, so the sorter runs `parseFloat("00:01:30:00")` → `0` for *every* row. All values compare equal, so the sort is a silent no-op. | High — looks like it works, doesn't |
  | 2 | **Size sorts lexically** | `helpers.py:548` stores `track.other_file_size[4]` — a human string like `1.2 GiB`. Column is `data-type="string"`, so `9.5 MiB` sorts above `10.2 GiB`. | High |
  | 3 | **Version sorts lexically** | `v10` sorts before `v9`. | Low |
  | 4 | Columns located by *header text* | `select_all_audio` / `deselect_all_audio` / the Screen-sort audio grouping do `findIndex(h => h.textContent.trim() === "Ext")`. Renaming a header silently breaks them. | Fragility, not a live bug |

  Corrections to my earlier draft of this list: the Name and Version columns are **not** affected by their `<img>` prefixes — `innerText` ignores image alt text, so those cells sort on their trimmed text as intended. Bug #1 (Duration) was missed in the first pass and is the most consequential of the four.

- [x] **Raw values are already available from pymediainfo** — no parsing of human-readable strings needed in Phase 3:
  - `track.file_size` → size in bytes (alongside the existing `other_file_size[4]`)
  - `track.duration` → duration in milliseconds (alongside `other_duration[4]`)

  This makes the Phase 3 fix for bugs #1 and #2 a two-line backend addition rather than a brittle string-parsing sorter. `audio_rate`, `audio_bits`, `audio_channels`, `width`, `height`, and `framerate` are already stored raw and sort correctly today.

**Test:** none — capture only.

---

## Phase 1 — Decouple data from the DOM *(code done — needs FULL CYCLE)*

The table currently *is* the data store. Fixed that first so the Tabulator swap is mechanical.

- [x] Module-level `scan_assets = {}` in `cn4m.js`, assigned from the sorted scan result in `handle_check_assets_progress`.
- [x] Consolidated the **four** duplicated extension arrays into shared `AUDIO_EXTS` / `IMAGE_EXTS` / `VIDEO_EXTS` consts plus a `normalize_ext()` helper (lowercases, strips a leading dot).
- [x] `select_all_audio` / `deselect_all_audio` collapsed into one `set_audio_selection(checked)` that reads `scan_assets[fileid].extension` via `is_audio_asset()`, instead of locating the Ext column by header text and scraping cell text.
- [x] The Screen / Stem audio-first sort now also uses `is_audio_asset(row.id)` (row id *is* the fileid), removing the last header-text column lookup — bug #4 is gone.
- [x] `remove_assets_from_table` prunes `scan_assets` alongside the DOM row.
- [x] `get_selected_assets` left checkbox-based (still returns fileids) — it becomes `getSelectedData()` in Phase 3.
- [x] Guarded the header-checkbox reset against `null` (it threw if no table was rendered yet).

**Automated check:** 18 assertions pass against a stubbed DOM — extension normalization (case + leading dot), icon mapping, `is_audio_asset` for unknown fileids and assets with no extension, select-audio touching only audio rows, deselect-audio preserving non-audio selections, and row removal keeping DOM and store in step. Harness kept in the scratchpad, not committed.

**Test:** FULL CYCLE — behavior must be *identical* to before. Pay attention to: SELECT ALL AUDIO after sorting by a few different columns, and deselect-audio when video rows are also selected (they must stay selected).

Suggested commit: `refactor: keep scan results in a JS data store instead of the DOM`

---

## Phase 2 — Vendor Tabulator *(code done — needs page-load check)*

- [x] **Tabulator 6.5.2** vendored into `app/static/` (MIT, zero dependencies — confirmed against the npm registry):
  - `tabulator.min.js` (436K, the **full** build — the core-only build is roughly a third the size, so all modules we need are included)
  - `tabulator_midnight.min.css` (30K, dark theme)
  - `tabulator.LICENSE.txt` — MIT license text kept alongside the code, since the repo is headed for open-sourcing
- [x] Wired into `app/templates/index.html`: script after `bootstrap.bundle.min.js` and **before** `cn4m.js`; stylesheet after `bootstrap.min.css` and **before** `cn4m.css`, so our overrides win the cascade in Phase 5.
- [x] Not used by any code yet — the table still renders exactly as before.

**Automated checks:**
- `Tabulator` registers as a browser global (`typeof Tabulator === "function"`) when loaded in a clean browser-like sandbox with no CommonJS `module`/`exports` in scope.
- **No style bleed:** every selector in the theme CSS is scoped under `.tabulator` — parsed the whole file and found zero unscoped selectors, so it cannot touch the existing UI.
- All static filenames referenced by `index.html` resolve to real files.
- `.gitignore` does not exclude the new files; the Dockerfile's `COPY . .` picks them up with no build step.

**Test:** hard-refresh http://localhost:5000. Expect: page looks **completely unchanged**, no console errors, and `typeof Tabulator` in the console returns `"function"`.

Suggested commit: `chore: vendor tabulator 6.5.2`

---

## Phase 2.5 — Raw sort fields in the backend *(done — verified in `assets.json`)*

Pulled forward from Phase 3 because it's independent of Tabulator and fixes bugs #1/#2 at the source.

- [x] Added `_as_number()` helper in `app/helpers.py` (coerces pymediainfo fields to int/float, `None` if non-numeric — some builds return strings).
- [x] `assets[fileid]["size_bytes"] = _as_number(track.file_size)` in the General branch.
- [x] `assets[fileid]["duration_ms"] = _as_number(track.duration)` in **both** the Video and Audio branches.
- [x] Verified additive-only: `assets.json` is a plain dict dump and `build_google_row` reads keys explicitly, so the Google Sheet output is unchanged and existing `assets.json` files need no migration (old entries simply lack the new keys).
- [x] `_as_number` unit-checked against int / numeric-string / float / `None` / `""` / `"N/A"` / non-scalar inputs.

**Test:** run a scan, then inspect `assets.json` in your workspace `repo/` folder — new entries should carry `size_bytes` (integer bytes) and `duration_ms` (milliseconds) alongside the human-readable `size`/`duration`. Image files should have `size_bytes` but no `duration_ms`. Then FULL CYCLE to confirm nothing regressed, and spot-check that the Google Sheet columns are unchanged.

Suggested commit: `feat: store raw size_bytes and duration_ms for sorting`

---

## Phase 3 — Swap the table rendering

The core phase. Replace the ~115-line template string + `makeTableSortable()` with a Tabulator instance.

- [ ] Transform `scan_assets` dict → array of row objects (`{fileid, parent, display_name, screen, version, is_version_up, extension, duration, video_codec, width, height, framerate, audio, audio_rate, audio_bits, audio_channels, size, dumbpath}`). Keep values **raw** — formatters handle display.
- [ ] Build `new Tabulator("#results", {...})` with best-practice config:
  - `data:` the array, `index: "fileid"` (so `deleteRow(fileid)` works),
  - `layout: "fitDataFill"`, `initialSort: [{column: "dumbpath", dir: "asc"}]` (or sort the array pre-load),
  - selection via `rowHeader: {formatter: "rowSelection", titleFormatter: "rowSelection", headerSort: false}`.
- [ ] Column definitions:
  - Name: formatter prepends file-type icon from `row.getData().extension` (not from cell text); sorter uses raw `display_name`.
  - Version: formatter prepends version-up/new-file icon from `is_version_up`; sorter on raw `version`.
  - Codec / Width / Height / FPS: formatters apply the existing QC logic (`qc_config`, `qc_resolution_rules`, `qc_resolution_fails` port over unchanged) — add a css class (e.g. `qc-fail`) + tooltip instead of inline styles.
  - Size **and Duration** (bugs #1/#2): **backend half already done** — `size_bytes` and `duration_ms` are now written by `check_asset` (see Phase 2.5 below). Remaining frontend work: columns display `size`/`duration` via `formatter` but sort on the raw field (`sorter: "number"` against `size_bytes` / `duration_ms`). Confirm image-only files and pre-existing `assets.json` entries — both of which lack the raw fields — sort to one end rather than throwing.
  - Version (bug #3): `sorter: "alphanum"` so `v9` < `v10`.
  - Screen / Stem: custom sorter reproducing audio-first ordering using `row.getData().extension`.
  - Numeric columns: `sorter: "number"`.
- [ ] Rewire actions to the Tabulator API:
  - `get_selected_assets()` → `table.getSelectedData().map(r => r.fileid)`,
  - `remove_assets_from_table(ids)` → `table.deleteRow(ids)` (+ prune `scan_assets`),
  - select/deselect-all-audio → `table.selectRow(table.getRows().filter(r => AUDIO_EXTS.includes(...)))` / `deselectRow(...)`,
  - post-transcode "uncheck everything" → `table.deselectRow()`.
- [ ] Keep the flags panel logic untouched.

**Test:** FULL CYCLE, plus specifically: Size now sorts by magnitude across KB/MB/GB; Version sorts by version value; re-running START replaces the table cleanly (call `table.destroy()` or `setData` on re-scan — pick one and verify no duplicate tables/listeners). Commit: `feat: render review table with tabulator`.

---

## Phase 4 — Delete legacy table code

- [ ] Remove `makeTableSortable`, `toggle_checkboxes`, the old DOM-scraping bodies of the audio helpers, and the table template string remnants.
- [ ] `grep -n "sortableTable\|review_checkbox\|makeTableSortable\|toggle_checkboxes" app/` → should only hit this file's history, not live code.

**Test:** FULL CYCLE. Commit: `chore: remove legacy table code`.

---

## Phase 5 — Theme pass

- [ ] Override `tabulator_midnight` in `cn4m.css` to match the app: `#222`/`#1a1a1a` backgrounds, `#606060` borders, striped rows, `fs-8`-equivalent font size, `#F99D38` accents on sort arrows/hover, red `qc-fail` = `#f87171`.
- [ ] Compare against the Phase 0 screenshots side-by-side.

**Test:** visual only + quick FULL CYCLE steps 3–7. Commit: `style: match tabulator theme to cn4m dark ui`.

---

## Phase 6 — The payoff features (one commit each, any order)

- [ ] **Header filters:** text filter on Folder/Name; `list`-editor dropdowns for Ext, Screen, Codec (values built from data); numeric `>=`-style filters on Width/Height/FPS. Verify actions operate on *selected* rows, not filtered-visible rows, and that "select all" while filtered only selects visible rows (Tabulator default — confirm it matches what we want).
- [ ] **QC filter:** stamp each row with a computed `qc_fail: true/false` during transform; add a "show failing only" toggle button next to the audio buttons.
- [ ] **Persistence:** `persistence: {sort: true, filter: true, columns: true}` + `persistenceID: "cn4m-review"` (localStorage). Verify a stale persisted layout doesn't hide new columns.
- [ ] **Spreadsheet feel:** `selectableRange`, `clipboard: true` for copy-out to Sheets/Excel. Confirm range-select doesn't fight row-selection checkboxes (Tabulator 6 supports both; test click interactions carefully).
- [ ] **Export:** small DOWNLOAD CSV button (`table.download("csv", ...)`).

**Test after each:** the feature itself + FULL CYCLE steps 6–8 (sort/select/approve still correct with filters active).

---

## Phase 7 — Docs & cleanup

- [ ] README: mention Tabulator + version in the stack notes; retake the review-table screenshot (also closes part of the "screenshots" item in TODO.md).
- [ ] Fold the Phase 0 known-bug notes into the commit history / delete this file when done.
