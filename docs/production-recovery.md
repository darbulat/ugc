Production images are built from a merged main commit after Lint and Test succeeds. The Publish production image workflow publishes the image to the repository's GHCR package and saves an identical deployment archive in a GitHub Actions artifact for 30 days. The archive permits delivery through the existing authenticated GitHub connection while registry access is provisioned for the production host.

Download the artifact for the intended main commit through authenticated GitHub Actions access. Verify the artifact digest returned by GitHub before extracting it. Transfer its image.tar.gz and manifest.json into a private staging directory on the production host. Validate the manifest revision against the merged commit and the successful workflow run before running the release command.

Run the checked-in release script from that same commit on the host. Choose only the services affected by the change. The application readiness release affects app, app_2, admin, max_bot and instagram_webhook.

```sh
python3 production_release.py /path/to/verified-artifact app app_2 admin max_bot instagram_webhook
```

The script takes the existing production deployment lock. It checks the archive SHA-256 and the loaded image's revision label, then resolves each container's current Compose configuration using its live environment. Previous rollout placeholders are reconstructed from their associated environment keys.

Release settings are saved under /opt/myapp/ugc-releases/<full-commit>/attempt-<unique-id>/ with directory mode 0700 and file mode 0600. compose.json contains the new image IDs. previous-compose.json retains the previous image IDs and health checks for rollback. Both files contain runtime secrets and belong in the encrypted recovery backup. Keep this directory outside public document roots and Git. The operational checkout, Compose files and environment file remain the sources inspected during preparation.

Each selected service is updated independently with dependency recreation and image builds disabled. Before replacing a Telegram replica the peer must be healthy. The script repairs a missing shared webhook through the surviving replica, waits for dependency readiness, checks that environment, mounts, networks, limits and security settings match the previous container, reloads nginx gracefully, and checks the public Mini App and admin routes. A failure rolls back all attempted services in reverse order. Previous images remain available locally.

After a verified rollout, /opt/myapp/ugc-releases/current points to its durable configuration. Use current/compose.json for subsequent deployments and recovery. Its explicit image IDs pin all captured services. Updating the operational environment requires a deliberate new release snapshot so the change can be reviewed. Each retry keeps its own preparation and rollback files, and the current pointer advances after successful verification.

Enable Docker live restore using configure_live_restore.py from the reviewed release. Provide the existing daemon configuration path, the installed dockerd binary and the current daemon PID. The helper merges the live-restore setting, validates the candidate with dockerd, checks for concurrent edits, replaces the configuration atomically and requests a SIGHUP reload. Verify LiveRestoreEnabled through docker info afterwards and verify that the daemon PID and running container IDs remain unchanged. A Docker restart requires a separately agreed maintenance window.

The readiness endpoints are available on the service network at app:9999/ready, app_2:9999/ready, admin:8001/ready, max_bot:8003/ready and instagram_webhook:8002/ready. HTTP 503 indicates unavailable required dependencies or incomplete initialization. The two-second probe deadline includes database connection acquisition and the Redis check for services using Redis storage.

Cold host startup, daemon crashes, database failure and restoration on another host require an isolated rehearsal followed by an agreed production maintenance window. Record recovery time, delivered alerts and any manual steps. PostgreSQL archive_mode changes require checking restart requirements and S3 capacity before activation.
