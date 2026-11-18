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

The November 18 audit observed archive_mode off, 16 MB WAL segments and archive_timeout of one minute. A quiet 42-minute sample generated approximately 0.5 MB of WAL records. Forced segment switches can still produce approximately 23 GB of uncompressed archive per day with activity every minute. The existing uploader sends full segments. Validate compressed segment uploads, retention and compatible PITR restoration before enabling continuous archiving within the 10 GB storage budget.

The operational recovery bundle is created by scripts/backup_recovery.py. It captures a fresh Compose snapshot and image inventory, the operational environment and configuration, backup credentials and restore dependencies, order images, TLS certificates, Docker configuration, and the checked CI source archive from the current release. A read-only container streams tar and gzip directly into age encryption. The host receives ciphertext. The age identity belongs in the owner's private storage, and the production host receives the public recipient.

The bundle is uploaded through the existing backup container's verified S3 client under recovery/ugc-recovery-<UTC timestamp>.tar.gz.age. Retention is seven days. Capacity is checked against the existing 10 GB bucket limit before upload. Only expired objects belonging to this recovery prefix are removed after a verified upload. Keep the existing database backup schedule alongside the recovery bundle. Their capture times are recorded separately, and restoration must reconcile database references, files and queued deliveries before resuming business processing.

Install the reviewed host scripts and the checksum-verified age binary under /opt/myapp/ugc-ops with owner-only permissions. Keep the producer image ID in its private recovery-image-id file. A regular run takes the deployment lock in shared mode and an exclusive recovery lock, captures the archive, verifies its S3 upload and retains local ciphertext for seven days. The chosen production schedule is every six hours. Existing alert configuration is managed separately.

Install the entry in config/recovery.cron in the deploy user's crontab after the first verified round trip. Preserve existing entries and avoid duplicating the recovery entry on retries. The verified host timezone is UTC, so runs occur at 03:20, 09:20, 15:20 and 21:20 Moscow time. Create the recovery-backup.log file with mode 0600 before enabling the entry.

After the first upload, download the encrypted object and compare its SHA-256 with the uploaded ciphertext. Decrypt it on the owner's machine using the age identity. Verify every archived file against the manifest inside the encrypted archive and check that configuration, source, certificates and order images are represented. The identity file must be available independently of the production server for future recovery.

The archive also captures the installed host scripts, public recipient, pinned producer image, age binary and private Compose reconstruction parameters from an explicit allowlist under /opt/myapp/ugc-ops. It excludes local archive history and the owner's private age identity. The current release manifest is saved as release-manifest.json alongside source.tar.gz so original CI checksums and registry digests survive restoration.

A host tool hotfix may come from a separately reviewed and tested merged commit. Record its revision separately from the application image and preserve the original CI application source. Archive the installed operational tools rather than assuming their version always matches the image. Parallel feature releases must not be downgraded or included solely to deliver an operational fix. Supply the reconstruction parameters only to the snapshot/backup process; do not change the monitored service.

An image removed from Docker for an exited historical job is recorded with unavailable metadata and its configured reference. Failure to inspect an image used by a running or otherwise active container still blocks the backup. During restoration, run any required migration using the verified application release image, rather than relying on an obsolete stopped migration container's image ID.

Resource and log policy
-----------------------

`config/production-resource-policy.json` covers 18 application and data services.
It excludes monitoring and alert delivery. Its memory ceilings total 12 GiB;
preflight requires at least 3.5 GiB of additional physical memory for the host
and excluded services. CPU ceilings are per service and intentionally allow
bursts shared across four host cores. These values came from the November 18
host audit, including cgroup memory peaks, Kafka's 1 GiB JVM heap and
ZooKeeper's 512 MiB heap. Reassess them before increasing workload. Available
host memory alone does not establish a safe limit for an individual service.

Install `apply_resource_policy.py` and this JSON policy in the private operations
directory alongside `production_release.py`. Preserve existing operations files
and record the merged source revision and installed SHA-256 values in
`installed.json`. The encrypted recovery bundle includes both new files.

```sh
python3 /opt/myapp/ugc-ops/apply_resource_policy.py plan \
  --policy /opt/myapp/ugc-ops/production-resource-policy.json
python3 /opt/myapp/ugc-ops/apply_resource_policy.py apply \
  --policy /opt/myapp/ugc-ops/production-resource-policy.json \
  --snapshot-environment /opt/myapp/ugc-ops/snapshot-environment.json
python3 /opt/myapp/ugc-ops/apply_resource_policy.py rotate \
  --policy /opt/myapp/ugc-ops/production-resource-policy.json \
  --snapshot-environment /opt/myapp/ugc-ops/snapshot-environment.json
```

`plan` only reads Docker and cgroup v2 data under the common deployment lock.
All services must be running and healthy. The host must have no swap. Proposed
memory must exceed the larger of current use and lifetime peak by at least
40%, and process counts must have at least twice their current headroom.
Existing stricter limits are preserved; legacy CPU quotas need manual review.
These checks repeat immediately before each live update. Never reset cgroup
peaks to bypass a rejected policy.

`apply` updates memory, CPU and process ceilings in place, without restarting
containers. It leaves memory reservations unchanged. It verifies container
identity, image, start time, restart count, memory events and all unrelated
runtime settings, then checks public routes. A failure stops the sequence and
restores attempted services in reverse order. Docker does not clear memory or
CPU limits when `docker update` receives zero; rollback for a formerly unlimited
service therefore restores physical host memory and CPU capacity, a combined
memory/swap ceiling equal to physical memory (the audited host has no swap),
and unlimited processes. Previously bounded limits are restored to their original
values; unlimited swap becomes the same effective no-swap ceiling. Inspect a failed attempt before
retrying; successful live updates are captured by subsequent release snapshots
rather than trusting stale Compose labels.

`rotate` requires the resource stage to be active first. It recreates only
`app` and `app_2`, one at a time, retaining each replica's existing image and
runtime configuration. A healthy peer is required before replacement. Readiness,
shared Telegram webhook, nginx reload and public checks follow each step. Each
replica is a separate verified stage; failure rolls back the attempted replica
and stops before the next one. All other services remain running.

The rotation policy retains five JSON files of approximately 20 MiB each per
container. A complete log record can exceed a size boundary. The JSON driver
preserves the existing collector integration. Existing containers require
recreation to activate new logging settings. No daemon restart, manual Docker
log edits or truncation is performed.

Each policy attempt keeps private previous and candidate Compose snapshots,
the unchanged application source and CI manifest, and policy operation metadata.
The `current` pointer advances after verification. The separate
`pending-logging-compose.json` prepares rotation for the remaining singleton
services; **do not deploy it wholesale**. Their activation requires a scheduled
service restart or an individually reviewed redundant deployment. Data services
must not be recreated merely to activate log rotation during a no-outage task.
Monitoring settings and monitoring container IDs are outside this policy.

The reserve server can host an independent physical PostgreSQL base backup and
compressed continuous WAL archive for PITR. A standby alone also replays accidental
writes and deletions. Define the acceptable recovery point and time, budget
archive retention, and prove restoration to an earlier time on the reserve
server before relying on this path. The existing logical S3 dumps remain useful
but do not supply the base backup required by WAL recovery. Activation, replication
credentials, retention safeguards and any primary restart belong in a separate
reviewed change; the log/resource rollout does not configure them.
