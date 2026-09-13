# cn4m files server

Serves the cn4m workspace read-only over plain HTTP, so the **Open in IINA / mpv**, **Preview** and **Copy URL** items on the tables' right-click menu have something to point at. It is [Caddy](https://caddyserver.com/) — a single, dependency-free `caddy.exe` — with the ten-line config in `Caddyfile`. Nothing here installs, registers or auto-starts anything: `serve.bat` runs the server in a console window until you press Ctrl+C.

See "Opening assets in a player" in the main README for how the whole thing fits together and how workstations are set up.

## Run it

Once, on the cn4m host:

```
get-caddy.bat       fetches the pinned Caddy release, verifies its SHA-512, unpacks caddy.exe here
```

Then whenever it should be up:

```
serve.bat           serves WORKSPACE_FOLDER (from the repo's .env) on port 2648, until Ctrl+C
```

It prints what it's serving and where. `http://<host>:2648/repo/` in a browser shows a directory listing, which is the quick way to confirm it's up and pointing at the right folder. Put `FILES_URL=http://<host>:2648` in cn4m's `.env` and the menu items appear.

Why it runs on the host and not in a container: reading the workspace through Docker Desktop's bind mount tops out around 200 MB/s — enough for one ProRes 422 HQ 4K stream with nothing to spare — while the same disk read natively does over 1 GB/s, which is 10GbE line rate.

## Settings

Both are environment variables, read by `serve.bat`:

| | |
|---|---|
| `CN4M_FILES_ROOT` | The folder to serve. Defaults to `WORKSPACE_FOLDER` from `..\..\.env`, which is the only reason to leave it unset. |
| `CN4M_FILES_PORT` | Port. Default `2648` — the next free one in the suite's block; see the port table in the main README. |

`caddy.exe` and downloaded zips are ignored by git. To move to a newer Caddy, change `VERSION` and `SHA512` together in `get-caddy.bat` (the hash is in `caddy_<version>_checksums.txt` on the release page) and re-run it.

## What's served

Everything under the workspace, exactly as it is on disk, with HTTP range requests (what players seek with) and a directory listing — except cn4m's `assets.json` and anything dot-prefixed (sync state, `.DS_Store`), which return 404.

**Trust.** Anyone who can reach the port can read every file in the workspace, with no login — the same model as the rest of cn4m, which assumes a trusted LAN, but unlike the SMB share this doesn't ask for Windows credentials. Don't expose the port beyond that LAN.
