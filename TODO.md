# TODO

- [ ] **Upgrade base image to `python:3.12-slim`** — `python:3.9-slim` is past end-of-life (google-auth warns about it at worker startup). Change the `FROM` line in the Dockerfile, then `docker compose build --no-cache` and test a full scan → approve → track cycle.
- [ ] **Pin dependency versions in `requirements.txt`** — currently unpinned; add loose bounds (e.g. `celery>=5,<6`, `Flask>=3,<4`) so public users get reproducible builds.
- [ ] **Per-preset output validation for transcodes** — `quarantine_and_transcode` currently treats a transcode as successful if ffmpeg exits without error and leaves a non-empty output file. That won't catch a run that exits 0 but produces the wrong thing (e.g. the old source-resolution HAP, or an output missing a video/audio stream). Add optional per-preset expectations to `config/ffmpeg_config.yaml` (e.g. expected resolution / that a video stream exists) and ffprobe the output against them in `run_ffmpeg_preset` before counting it as complete. Would make the "don't quarantine until transcode is actually complete" guarantee much stronger.

## Before open-sourcing

- [ ] Rotate the Google service-account key and Discord webhook (old values are in git history)
- [ ] Scrub git history of `.env` (fresh repo with a clean initial commit, or `git filter-repo --path .env --invert-paths`)
- [ ] Add a LICENSE file (MIT?)
- [ ] Add screenshots to the README (`docs/screenshots/`)
