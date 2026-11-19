# Encrypted PITR archive on the shared reserve host

This release adds an asynchronous PostgreSQL 16 archive on Timeweb
`194.87.131.138`. It does not fail over production, restart its database, change
application containers, or configure alerts. Existing S3 backup jobs and
Timeweb applications remain in place. Continuous encrypted WAL in this first
release resides on Timeweb; it is not automatically mirrored to S3.

A base backup contains the **whole production PostgreSQL cluster**, not just the
`ugc` database. WAL records subsequent changes. A base completed before the
chosen timestamp plus an uninterrupted WAL chain allows recovery to that
point. Redis, uploaded media, application code, external payments and third
party state require their existing separate backups and reconciliation.
Restoring PostgreSQL does not reverse external side effects.

## Resource and isolation contract

- `ugc-pitr.slice` limits the **combined** receiver and base-backup processes to
  256 MiB RAM, zero swap, 25% of one CPU and 64 tasks. PostgreSQL clients are
  already installed on the reserve. No Docker or global PostgreSQL packages
  are installed there.
- Only `/opt/ugc-pitr`, `/etc/ugc-pitr`, `/var/lib/ugc-pitr` and
  `/var/lib/ugc-pitr-restore`, a new `ugc-pitr` account, and the five new
  `ugc-pitr*` units are created, plus their private temporary runtime directories
  under `/run`. The operator never runs mutating commands
  against other units. It compares their PIDs, start times and resource caps
  before and after each activation.
- The archive has an 8 GiB budget and requires 16 GiB free on the host.
  Base backups require at least 2 GiB available RAM and use a spread checkpoint
  and 5 MiB/s data-transfer cap. PostgreSQL does not apply that cap to WAL
  streaming. Reassess these limits if the cluster exceeds 1 GiB or gains
  additional tablespaces.
- An isolated acceptance restore is temporary: 768 MiB RAM, half one CPU,
  no TCP/network access, private socket port 16544, a private filesystem from
  the audited production PostgreSQL/PostGIS image, and only its own recovery
  directory writable. It never connects to the reserve's existing databases.
  At least 3 GiB available host RAM is required. The instance stops after
  15 minutes; after successful verification it is stopped and its plaintext
  data removed. This is a copy verification, not a production outage drill.
  The WAL fetch helper sets its own `/usr/bin:/bin` command path, independent
  of the host systemd search path and the public image's Docker entrypoint.

## Primary access and bounded WAL retention

The reserve generates its own SSH tunnel key. Its public key on the primary
`deploy` account has `restrict`, a source-IP restriction and a forced allowlist: only
a PostgreSQL stdio relay to `127.0.0.1:65432` or the backup gate. OpenSSH
forwarding, PTY, agent access and arbitrary shell commands are disabled. The
reserve relay listens only on `127.0.0.1:16543`, with at most four connections.
Pin the primary's already verified host key; do not accept a keyscan blindly.

The dedicated `ugc_pitr_v1` role has LOGIN/REPLICATION and three required control
functions, not superuser, role creation, database creation or application table
privileges. Its password travels only as an age-encrypted bootstrap. Each
archive is encrypted for both the owner's existing recovery public key and a
new private reserve PITR identity. The owner's private identity stays on the
owner's Mac. The reserve identity and PostgreSQL/tunnel credentials are root
only; systemd passes only required credentials to each unit.
Because systemd credentials can have mode 0440, each database-client service
copies its bounded password file to mode 0600 under its private 0700
`RuntimeDirectory` in `/run`. The original credential is preserved. Normal or
failed execution removes the temporary copy; systemd removes the runtime
directory when the unit stops, including after a hard process termination.

The primary uses the existing replication settings (`wal_level=logical`, four
senders and four slots), so this release requires **no database restart**.
`max_slot_wal_keep_size=2GB` is reloaded and checked with unchanged container
identities/start times. This limit applies at checkpoints; it is not a strict
filesystem quota. A long receiver outage or high WAL volume can invalidate its
slot. Do not silently recreate a broken recovery chain: investigate and make a
new verified base. The primary is never made dependent on remote commits:
`synchronous_standby_names` stays empty. `pg_receivewal --synchronous` fsyncs
received bytes locally and does not enable synchronous primary replication.

The audit also records the names and sources of pending restart settings.
An existing `max_replication_slots` file/command-line mismatch alone is allowed
when the active value comes from the command line and still has the required
spare capacity. PostgreSQL can first report this mismatch after a reload.
The file value is preserved; PITR uses the live slot count without a restart.
Any other pending setting, unverified source or insufficient live capacity
still blocks activation and requires separate review.

Completed 16 MiB segments are compressed, encrypted and atomically published
with checksums. A WAL switch is requested every five minutes when there is WAL
activity. Consequently the completed encrypted chain normally trails by up to
roughly five minutes plus transfer/processing; no zero-data-loss claim is made.
Partial current segments are private plaintext on the reserve. A stopped
receiver, exhausted budget, cluster/timeline mismatch or missing/corrupt WAL
fails closed; it must not be described as healthy PITR. Status is recorded at
`/var/lib/ugc-pitr/archive/status.json`; wiring it into alerts is separate work.

Retention keeps seven days, a base before the boundary, and at least two bases.
WAL needed by the oldest retained base is preserved. Capacity pressure stops
archiving rather than deleting a required chain to make space.

## Staged activation from a reviewed main commit

1. Merge only after PR CI and code review, then require the merged main CI.
   Record the exact revision and checksums. Preserve dirty production checkouts
   and existing `/opt/myapp/ugc-ops` tools; install only the new primary helper
   beside them. No application rebuild or Compose update is needed.
2. Read current primary and reserve state again. Wait for the currently
   announced neighboring rollouts to finish. Use an existing individually
   provisioned owner SSH key when already authorized. For a new operator,
   obtain an explicitly approved restricted key whose forced command is
   `/usr/bin/python3 -Es /opt/ugc-pitr/releases/<revision>/pitr_operator.py`.
   A new restricted key has no forwarding, PTY, agent access or general shell.
3. Install only the new reserve files/units. `pitr_operator.py install` requires
   the full main revision and the trusted primary `known_hosts` entry. Record
   existing unit state, generate reserve keys, and pass only public recipients
   and the public tunnel key to `pitr_primary.py provision`. Provisioning holds
   the common production deployment lock and returns encrypted bootstrap data.
   It never prints database credentials or changes application schemas.
4. Import the encrypted bootstrap on the reserve and start the receiver only.
   Inspect the shared 256 MiB cgroup limit, source role/slot and healthy core
   services before proceeding.
5. **First base only after neighboring deployments finish.** The restricted
   `ugc-pitr-backup-lock` SSH command holds the common deployment lock shared
   and a dedicated base lock exclusive. The base service refuses concurrent
   deployment/base activity, insufficient headroom or an oversized cluster.
   Daily scheduling remains disabled until acceptance succeeds.
6. Run `pitr_primary.py probe --token <16 hex>` under the deployment gate. This
   creates two temporary NOLOGIN role markers around a timestamp; it changes
   no application/customer records. Save its private JSON on the reserve and
   wait for all required encrypted WAL. Prepare a new isolated directory and
   import a filesystem export of the exact public PostgreSQL image, without
   database volumes. Never extract the image into the host root filesystem.
7. Start only `ugc-pitr-restore.service`. Prove it is still in recovery, paused
   at the target, has the same cluster identity, contains the before marker
   and excludes the after marker, and can load PostGIS. Do not promote it.
   Stop it, save verification evidence, remove its owned plaintext directory,
   and remove only the two marker roles on the primary.
8. Enable the receiver and daily base timer after proof. Recheck original
   production postmaster start time and neighbor unit PIDs/configuration.
   Keep private bootstrap/rollback state and encrypted archives owner-only.

Rollback or cleanup touches only these new PITR units, role, slot and exact SSH/
HBA grants. Stop the base and receiver before dropping their slot. Restore only
this installation's previous WAL-retention value; do not overwrite concurrent
HBA/SSH edits. No database restore, container restart, volume removal or
production failover belongs to this installation workflow. Any production
restore/outage/restart requires separate owner agreement.

## Validation

`tests/monitoring/check_pitr.sh` uses synthetic isolated PostgreSQL containers:
real streaming, limited replication role, full `pg_verifybackup`, encrypted base
and WAL, deliberate missing-segment rejection, and recovery of a deleted row
to a paused target without promotion. The client has a 256 MiB cgroup limit.
The dedicated client image adds server verification tools only to the CI
fixture. Unit tests cover timing/base selection, checksum authentication,
retention dependencies, path isolation, resource/configuration guards and
rejection of commands against neighboring services. A real systemd harness
uses synthetic credentials under an unprivileged account and confirms both
private libpq file permissions and runtime cleanup after normal and hard-kill
termination. Its temporary units are isolated, bounded and collected afterward.

References: [PostgreSQL 16 pg_receivewal](https://www.postgresql.org/docs/16/app-pgreceivewal.html),
[pg_basebackup](https://www.postgresql.org/docs/16/app-pgbasebackup.html),
[systemd.exec](https://www.freedesktop.org/software/systemd/man/256/systemd.exec.html).
