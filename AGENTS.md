# Project agent notes

## Deployment server

- Host: `31.59.106.143`.
- SSH account: `root` (key-based access; use the configured local SSH identity).
- Application checkout: `/opt/myapp/ugc`.
- Docker Compose project: `ugc`.
- Observed active Compose files: `docker-compose.yml` and `docker-compose.dev.yml`. Confirm the live configuration before deploying because the server checkout may change.
- The server checkout is on `ops/selectel-storage-20261106` and has local modifications and untracked operational files. Do not run `git reset`, `git clean`, overwrite its checkout, or build a release from that dirty working tree.
- Build/deploy from a clean release source or archive, and update only the services required by the change. The admin service is separate from `app` and `app_2`; an admin-only change can usually be deployed by rebuilding/recreating `admin` alone.
- Never print, copy into logs, or commit `/opt/myapp/ugc/.env`, credentials, or private SSH keys.
