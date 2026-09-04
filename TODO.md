# TODO

- [ ] **Decide how to handle descriptionless filenames like `IntroIndianapolis_v01.mp4`** — the version isn't parsed out of these. Both patterns in `parse_asset_filename` require at least three underscore-separated segments (`{id}_{desc}_{screen}_{version}` and the `{id}_{desc}_{version}` fallback), because `desc` is a required group. A two-segment name matches neither, so it falls to the non-conforming branch: `version=''` and `display_name` set to the whole stem — the version stays visible in the NAME column and the VERSION cell is blank. Knock-on effect: `basename` also becomes the full stem including `_v01`, so version-up detection never fires and a later `_v02` reads as a separate new asset rather than a version-up ☝️.

  Options: (a) rename to fit the convention — `Intro_Indianapolis_v01.mp4` parses correctly today, no code change; or (b) add an `ASSET_FILENAME_PATTERN_NO_DESC` for `{id}_{version}.{ext}`, tried *last* so nothing that parses today changes:
  ```python
  ASSET_FILENAME_PATTERN_NO_DESC = re.compile(
      r'^(?P<id>[A-Za-z0-9][A-Za-z0-9_.\-]*[A-Za-z0-9]|[A-Za-z0-9])'
      r'_(?P<version>v[0-9][^.]*)'
      r'\.[^.]+$',
      re.IGNORECASE
  )
  ```
  **Migration caveat for option (b):** files of this shape already in `assets.json` were stored with the old full-stem `basename`. After the change, a re-scan computes a *different* basename for them, so they won't match their own history — expect a spurious 🆕 on what should be a version-up. Worth auditing how many existing entries are affected before deciding. Also update the "Filename convention" section of the README either way.

- [ ] **Upgrade base image to `python:3.12-slim`** — `python:3.9-slim` is past end-of-life (google-auth warns about it at worker startup). Change the `FROM` line in the Dockerfile, then `docker compose build --no-cache` and test a full scan → approve → track cycle.
- [ ] **Pin dependency versions in `requirements.txt`** — currently unpinned; add loose bounds (e.g. `celery>=5,<6`, `Flask>=3,<4`) so public users get reproducible builds.
- [ ] **Per-preset output validation for transcodes** — `quarantine_and_transcode` currently treats a transcode as successful if ffmpeg exits without error and leaves a non-empty output file. That won't catch a run that exits 0 but produces the wrong thing (e.g. the old source-resolution HAP, or an output missing a video/audio stream). Add optional per-preset expectations to `config/ffmpeg_config.yaml` (e.g. expected resolution / that a video stream exists) and ffprobe the output against them in `run_ffmpeg_preset` before counting it as complete. Would make the "don't quarantine until transcode is actually complete" guarantee much stronger.

- [ ] **Integrate renaming with cn4m-symmetry** — the review pane's right-click **Rename…** renames only the file in the cn4m repo (`rename_asset` in `app/tasks.py`: `os.rename` within the asset's own folder, then a re-scan). Where the repo file is a symlink placed by cn4m-symmetry, the source keeps its original name and the two diverge from that point on — which is fine for a one-off version fix, but wrong if the original name matters downstream. Worth making the rename comprehensive: rename the source, then the link, so both stay in step.

  Open questions: whether cn4m should reach into symmetry's tree directly or ask symmetry to do it (the worker would need write access either way); what to do when a rename half-succeeds; and whether the UI should say up front that a row is symlinked, so the choice isn't hidden behind a caveat in the README. Until then, the Renaming section of the README documents the limitation.

## Before open-sourcing

- [ ] Rotate the Google service-account key and Discord webhook (old values are in git history)
- [ ] Scrub git history of `.env` (fresh repo with a clean initial commit, or `git filter-repo --path .env --invert-paths`)
- [ ] Add a LICENSE file (MIT?)
- [ ] Add screenshots to the README (`docs/screenshots/`)
