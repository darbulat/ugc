# Project agent notes

These notes are for anyone developing this repository and deploying it to the production server. Recheck live state before acting; server details below were last observed on 2026-11-10.

## Server and access

- Host: `31.59.106.143`.
- SSH account: `deploy`, key-based access. This account has Docker access. Use an individually provisioned SSH key; never put private keys in this repository or send them through chat.
- Application checkout and Compose project directory: `/opt/myapp/ugc`.
- Compose project name: `ugc`.
- The running containers were configured with `/opt/myapp/ugc/docker-compose.yml` and `/opt/myapp/ugc/docker-compose.dev.yml`. Confirm the current container labels and service/image mapping before deploying; do not assume the repo's `docker-compose.prod.yml` exists on the server.
- The server checkout was on `ops/selectel-storage-20261106` and had local modifications and untracked operational files. Treat this checkout as operational state: do not `git checkout`, `git pull`, `git reset`, `git clean`, overwrite files, or use it as a build context. If it has changed, preserve its state and ask before modifying it.
- Never print, copy into logs, or commit `/opt/myapp/ugc/.env`, credentials, database dumps, or private SSH keys.

## Development workflow

1. Read this file and inspect the relevant service, tests, migrations, and current Git status before editing.
2. Start from the latest `origin/main`; create a topic branch or isolated worktree. Do not develop directly on `main`.
3. Keep changes focused. Add or update tests for behavior changes. For database changes, include an Alembic migration and consider compatibility with the currently deployed version during a rolling update.
4. Install project dependencies with `uv sync --all-extras`. Run the relevant focused tests, then use the repository checks as appropriate: `make format-check lint typecheck test`. `make test` excludes tests marked `e2e`; run the relevant E2E suite when the change affects browser flows or an external integration.
5. Push the topic branch and open a PR. Wait for GitHub CI and code review; resolve findings before merging. Deploy production changes from a commit that has been merged to `main`, unless the owner explicitly asks for a different release process.

## Production deployment

The repository README documents `make deploy-apps` and `scripts/deploy_apps_zero_downtime.sh` for rolling `app` then `app_2`; the script builds once and waits for each instance to become healthy. That procedure assumes its Compose files and build context match the live server. The current server checkout is dirty, so do not run the script from `/opt/myapp/ugc` against its default `.` build context.

For a release, use a clean source tree/archive from the intended merged commit and keep the server's Compose files and `.env` in place. One safe way to transfer source from a local checkout is:

```bash
git fetch origin main
REV=$(git rev-parse origin/main)
REL="/tmp/ugc-release-${REV:0:7}"
git archive --format=tar "$REV" | ssh deploy@31.59.106.143 \
  "mkdir -p '$REL' && tar -xf - -C '$REL'"
```

On the server, create a temporary Compose override whose `build.context` points to that clean release directory for each service being rebuilt. Run Compose from the server project configuration, preserving project name `ugc`, the confirmed live Compose files, and `/opt/myapp/ugc` as `--project-directory`. Do not replace the server checkout or its Compose/environment files with the release archive.

For the observed admin-only deployment, the override and commands were:

```yaml
services:
  admin:
    build:
      context: /tmp/ugc-release-<short-sha>
      dockerfile: Dockerfile
```

```bash
cd /opt/myapp/ugc
docker compose -p ugc --project-directory /opt/myapp/ugc \
  -f /opt/myapp/ugc/docker-compose.yml \
  -f /opt/myapp/ugc/docker-compose.dev.yml \
  -f /tmp/ugc-release-<short-sha>-compose.yml build admin
docker compose -p ugc --project-directory /opt/myapp/ugc \
  -f /opt/myapp/ugc/docker-compose.yml \
  -f /opt/myapp/ugc/docker-compose.dev.yml \
  -f /tmp/ugc-release-<short-sha>-compose.yml up -d --no-deps admin
docker inspect ugc-admin-1 --format '{{.State.Status}} {{.State.Health.Status}}'
```

Replace the placeholder with the release ID and put the YAML above in the named override file. If live Compose files or service names have changed, adapt the commands only after verifying them.

Deploy only affected services:

- **Admin-only change:** `admin` is a separate service. Build it from the clean release context, then run `docker compose ... up -d --no-deps admin`. Confirm `ugc-admin-1` is running and healthy before finishing. This was the procedure used for the paid-order admin update.
- **Webhook app:** use the zero-downtime sequence for `app` and `app_2` from the repo script after confirming the live Compose service/image mapping. Keep at least one healthy instance serving traffic while updating the other.
- **Other workers/services:** identify all services using the changed code/image and update only those required. Do not assume that rebuilding `app` updates workers already running an older image.

Before deployment, inspect Compose project/config labels and the affected service names without dumping the full resolved configuration, which may contain secrets. If the release contains migrations, confirm they are backward-compatible with the old and new app versions, take the configured backup, and run the migration once using the repository migration service before or during rollout as the migration requires. Do not ignore a migration failure.

After deployment, check container health, startup logs with secrets excluded, and a relevant application smoke check. Keep the prior image/release available until verification succeeds so rollback is possible. Do not remove volumes, run `down -v`, restore a database, or make unrelated infrastructure changes as part of an application deploy.

The GitHub workflow `deploy-dev-e2e.yml` is for the dev contour and depends on GitHub secrets. It is not authorization or configuration for production deployment to this host; confirm the workflow target before using it.
