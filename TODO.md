# TODO

- [ ] **Upgrade base image to `python:3.12-slim`** — `python:3.9-slim` is past end-of-life (google-auth warns about it at worker startup). Change the `FROM` line in the Dockerfile, then `docker compose build --no-cache` and test a full scan → approve → track cycle.
- [ ] **Pin dependency versions in `requirements.txt`** — currently unpinned; add loose bounds (e.g. `celery>=5,<6`, `Flask>=3,<4`) so public users get reproducible builds.

## Before open-sourcing

- [ ] Rotate the Google service-account key and Discord webhook (old values are in git history)
- [ ] Scrub git history of `.env` (fresh repo with a clean initial commit, or `git filter-repo --path .env --invert-paths`)
- [ ] Add a LICENSE file (MIT?)
- [ ] Add screenshots to the README (`docs/screenshots/`)
