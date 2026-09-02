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

**Gotcha found during this phase — template caching.** `typeof Tabulator` came back `undefined` even though the file served fine (200, full 445,984 bytes). Cause: Flask was serving a *cached compiled template*, so the new `<script>` tag never reached the browser. `docker-compose.yaml` sets `FLASK_ENV=development`, but that variable has been a **no-op since Flask 2.3** (running 3.1.3 here), so `app.debug` was `False` and `jinja_env.auto_reload` with it. Static files (`.js`/`.css`) are read from disk per request — which is why the Phase 1 `cn4m.js` work appeared without a restart and this didn't.

Fixed durably by setting `app.config["TEMPLATES_AUTO_RELOAD"] = True` in `app/__init__.py` (verified `True` at runtime). **Any future `index.html` edit — e.g. the Phase 6 filter/download buttons — now takes effect on refresh with no restart.** Deliberately did *not* switch on full debug mode, which would also enable the interactive debugger.

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

## Phase 3 — Swap the table rendering *(code done — needs FULL CYCLE)*

- [x] `asset_rows()` flattens the scan dict into Tabulator's row array, keeping values **raw** (`display_name || basename || name` fallback preserved).
- [x] `render_asset_table()` builds the table on the first scan and calls `replaceData()` on later scans, so column widths (and Phase 6 filters) survive a re-scan.
- [x] Table config: `index: "fileid"`, `layout: "fitDataFill"`, `selectableRows: true`, `rowHeader` checkbox column (frozen, 40px), `placeholder: "No new assets found."`.
- [x] Formatters ported unchanged in behaviour: file-type icon on Name, version-up/new-file icon on Version, QC red on Codec / Width / Height / FPS via a `.qc-fail` class instead of inline styles, `&nbsp;` folder spacing.
- [x] **Bug #1 (Duration) and #2 (Size) fixed** — `raw_number_sorter()` sorts on `duration_ms` / `size_bytes` while the column displays the human-readable value. **Bug #3 (Version)** fixed with `sorter: "alphanum"`.
- [x] Rewired to the Tabulator API: `get_selected_assets` → `getSelectedData()`, `remove_assets_from_table` → `deleteRow()` (guarded by `getRow()` so an already-removed row is a no-op), `set_audio_selection` → `selectRow`/`deselectRow` over `getRows("active")`, transcode resets → `deselectRow()`.
- [x] Added `escape_html()` and applied it to every formatter — filenames and folder names are user-supplied and were previously interpolated straight into markup.
- [x] Minimal `.qc-fail` / `.cell-icon` CSS added; full theming is Phase 5.

**Automated checks:** 32 assertions pass — row transform and name fallbacks, both sort-bug fixes, missing raw fields sorting to one end without throwing, audio-block screen sort, every QC formatter (pass / fail / empty, per-screen resolution rules, float FPS tolerance), icon selection, folder spacing, and HTML escaping of markup in filenames.

**Test:** FULL CYCLE. Specifically:
- **Duration and Size now sort correctly** — previously Duration did nothing and Size sorted alphabetically.
- Re-run START twice: the table should refresh, not stack or duplicate.
- Approve/quarantine a row, then re-scan — no ghost rows.
- SELECT ALL AUDIO, then approve, and confirm the right files moved.

**Two judgement calls to review:**
1. `maxHeight: "75vh"` — long scans now scroll *inside* the table (and get virtual rendering) rather than the page growing. One line to remove if you'd rather the page scroll.
2. The old table's Bootstrap classes (`table-dark table-striped table-sm fs-8`) are gone; Tabulator's midnight theme is in charge until Phase 5, so **expect the styling to look off** — that's the next phase, not a regression.

Suggested commit: `feat: render review table with tabulator`

---

## Phase 4 — Delete legacy table code *(code done — needs FULL CYCLE)*

- [x] Removed `makeTableSortable()` — the hand-rolled DOM sorter, dead since Phase 3.
- [x] Removed `toggle_checkboxes()` — Tabulator's `rowSelection` header does this.
- [x] Removed `is_audio_asset(fileid)` — `makeTableSortable` was its only caller; `is_audio_ext(ext)` remains and is used by the screen sorter and audio selection.
- [x] **Removed `scan_assets` entirely.** With `is_audio_asset` gone nothing read it, leaving it write-only. The Tabulator instance now *is* the data model — a parallel store would only be a desync risk. This retires the Phase 1 scaffold, which had done its job of getting the data off the DOM.
- [x] Updated the file header comment, which still described hand-rolled sorting and checkbox selection.
- [x] Verified: no live references to `sortableTable`, `review_checkbox`, `makeTableSortable`, `toggle_checkboxes`, `scan_assets`, `is_audio_asset`, or `data-type=` anywhere under `app/`.
- [x] Swept every remaining function for reachability — all are either called or passed as formatter/sorter values in the column defs.
- [x] Re-ran the Phase 3 suite against the trimmed file: **32/32 still pass.**

Net: `cn4m.js` is **581 lines, down from 656** — and that includes everything Tabulator added.

**Test:** FULL CYCLE. This phase only deletes unreachable code, so any difference from the Phase 3 build is a real regression worth reporting.

Suggested commit: `chore: remove legacy table code`

---

## Phase 5 — Theme pass *(code done — needs your eyes)*

Tuned for the stated priority: hundreds of rows, scannable at a glance, QC flags must pop.

- [x] **Rows much darker, striping barely there.** The theme shipped `#666` rows with `#444` stripes — very light and high-contrast, which is what read as wrong. Now `#1b1b1b` / `#1f1f1f`: darker than the `#222` panel, so the table reads as recessed, with just enough stripe to track across 16 columns.
- [x] **All grid borders removed** — cell dividers, header rule, table outline, frozen-column divider. Separation now comes from spacing and colour alone.
- [x] **Padding cut** — cells `1px 5px` (was `4px`), row min-height 18px (was 22px). Cells are single-line with ellipsis, so one long filename can't make a tall row and break the rhythm.
- [x] **Smaller, lighter type** — `0.72rem` / weight 300 body (was 14px / normal, and 0.7625em previously). Headers are `0.66rem`, uppercase, letter-spaced, muted `#8a8a8a`, so they read as labels rather than competing with data.
- [x] **QC failures carry the only strong colour** — brighter `#ff6b6b`, weight 500, on a faint tinted chip, so a failing cell is findable by *shape* as well as colour when skimming.
- [x] **Selection uses obx orange** (`rgba(249,157,56,.16)`) — it's the primary action, and the tint stays legible across striping and hover.
- [x] Sort arrows shrunk to 4px and recoloured — inactive `#4a4a4a`, active obx orange.
- [x] Dark scrollbar, muted empty-state text, brand-orange checkbox via `accent-color`.

**Careful bit:** the sort arrows are CSS triangles built *from borders*, so "remove all borders" had to be done selector-by-selector rather than with a blanket rule — a global `border: none` would have deleted the arrows entirely.

**Automated check:** every override was verified to match or beat the theme's selector specificity (it loads after `tabulator_midnight.min.css`), so nothing silently loses the cascade. The theme's only `!important` rules are on column-calculation rows, which this table doesn't use.

**Test:** run a scan and look at it. Knobs, all one-liners:
- stripe intensity → `.tabulator-row.tabulator-row-even` background
- density → `.tabulator-row .tabulator-cell` padding + `.tabulator-row` min-height
- if the QC chip reads as too busy → drop `background-color`/`padding` from `.qc-fail`, keeping the colour and weight

**Follow-up tweaks after review (all committed with the theme):**
- Font up to `0.78rem` body / `0.70rem` headers, stripe contrast up to `#1b1b1b` vs `#272727` — two rounds of nudging from the initial values.
- Vertical breathing room: cell padding `3px 5px`, row min-height 20px. Icon-to-text gap `6px` via `.cell-icon` margin.
- **`layout: "fitDataFill"` → `"fitDataStretch"`** — manual column resizes were snapping back. The `fitData`/`fitDataFill`/`fitDataTable` layouts share one function that calls `reinitializeWidth()` *unconditionally*, and that method starts with `this.widthFixed = false`, wiping the manual width. `fitDataStretch` is the only variant that guards it (`e.widthFixed || e.reinitializeWidth()`). Side effect: the last visible column (Size) stretches to fill leftover width.
- `maxInitialWidth` on Folder/Name/Screen (260/340/180) so one long filename can't blow out the initial layout; `minWidth: 90` on Size so its header is readable by default.
- **Opaque frozen header cell** — the transparent-header rule left the sticky checkbox column see-through, so column headers scrolled visibly underneath it. Fixed with `#222` on `.tabulator-col.tabulator-row-header` (4-class selector, verified to beat the 3-class transparent rule).

Suggested commit: `style: match tabulator theme to cn4m dark ui`

---

## Phase 6 — The payoff features (one commit each, any order)

- [x] **Header filters** *(done — needs testing)*: contains-filter on Folder/Name, `list` dropdowns on Screen/Ext/Codec (`valuesLookup: true`, built from the full data set so narrowing one column never removes options from another), `>=` number filters on Width/Height/FPS.
  - **Select-all is NOT filter-aware by default** — the header checkbox calls `selectRow(rowRange)` and with no `rowRange` that resolves to *every* row in the table. Set `titleFormatterParams: { rowRange: "active" }` to get the agreed visible-only behaviour. (`"visible"` would have been wrong too — under the virtual DOM that means only rows rendered in the viewport.)
  - `sortValuesList` and other params from older docs don't exist in 6.5.2; verified every param against the bundle before using it. Dropdown values therefore come in data order.
  - Header filter inputs restyled — the theme ships them light (`#444` on `#999`), which clashed badly with the flat dark UI.
  - **Follow-up: counter was one filter-change stale.** `dataFiltered` is dispatched from *inside* Tabulator's filter routine, before the filtered set is assigned to `activeRows` — so `getRows("active")` in that handler reads the *previous* filter state. The event's second argument carries the fresh set; `update_selection_count()` now takes it as a parameter and falls back to querying the table when called from `rowSelectionChanged`.
  - **Follow-up: every column is now filterable**, and the numeric ones take comparison operators — `2992` (exact), `>3000`, `>=3000`, `<3000`, `<=3000`, `!=1080`. Implemented as a custom `headerFilterFunc` over an `input` filter (a `number` input won't accept `>`). Duration and Size filter against their raw fields in familiar units — seconds and MiB — rather than ms and bytes.
    - Empty values are excluded from numeric filters. This needed an explicit guard: `Number(null)` and `Number("")` are both `0`, so an audio file with no width would otherwise have matched a `<1000` width filter. Caught by test, not by eye.
    - A partially typed filter (`>` alone, or junk) hides nothing rather than emptying the table mid-keystroke.
  - **Added a selection counter** next to the action buttons: selection survives a filter change, so a row can be selected while hidden. It reads `12 selected (3 hidden by filter)` when that happens — approve/quarantine move real files, so silent hidden selections were worth guarding against. Drop the `#selection_count` span and its two handlers if it's noise.
- [ ] **QC filter:** stamp each row with a computed `qc_fail: true/false` during transform; add a "show failing only" toggle button next to the audio buttons.
- [ ] **Persistence:** `persistence: {sort: true, filter: true, columns: true}` + `persistenceID: "cn4m-review"` (localStorage). Verify a stale persisted layout doesn't hide new columns.
- [ ] **Spreadsheet feel:** `selectableRange`, `clipboard: true` for copy-out to Sheets/Excel. Confirm range-select doesn't fight row-selection checkboxes (Tabulator 6 supports both; test click interactions carefully).
- [ ] **Export:** small DOWNLOAD CSV button (`table.download("csv", ...)`).

**Test after each:** the feature itself + FULL CYCLE steps 6–8 (sort/select/approve still correct with filters active).

---

## Phase 7 — Docs & cleanup

- [ ] README: mention Tabulator + version in the stack notes; retake the review-table screenshot (also closes part of the "screenshots" item in TODO.md).
- [ ] Fold the Phase 0 known-bug notes into the commit history / delete this file when done.
