# Independent UMC monitoring

This monitor runs on the separate `reels-editing-01` Timeweb VPS. It does not
import the UMC application, install Docker, open a listener, or restart any
existing project. Python 3.12+ and the existing SSH client are sufficient.

## Checks and notifications

- Check `/miniapp/app.html` and `/admin/login` over HTTPS every 30 seconds.
  Require both HTTP 200 and the expected page content. Redirects, invalid TLS,
  timeouts and unexpected bodies fail the check. `/health` at the public nginx
  is deliberately excluded: it returns a static 200.
- After two consecutive failures, group the affected checks into one Telegram
  message. Transient single failures are silent. Repeat unresolved incidents
  after four hours. Send recovery only for incidents previously delivered.
- Persist incident state atomically. Do not acknowledge a notification until
  Telegram returns `ok: true`; retry failed delivery after five minutes.
- Use a dedicated bot owned by Kamil, posting to the private `Server Alerts`
  channel subscribed to by Kamil and Bulat. Existing alerts to Bulat are
  unchanged. The application's Telegram/MAX bots and their webhooks are not
  touched. There are no `getUpdates`, webhook changes or user broadcasts.
  Bot identity is confirmed by `getMe.is_bot` and an exact configured username
  match, rather than inferred from a username suffix.

The optional production reporter additionally checks Docker on the host,
healthy app replicas, and the existing internal admin `/health` response,
including the result of `SELECT 1`. That endpoint is accessed inside the
existing admin container; no public readiness endpoint is introduced.

The reporter checks logical and physical S3 backups every ten minutes. Failed
queries are retried after one minute; only three distinct failed attempts
make the S3 check unhealthy. Repeated reads of the same cached failure do not
increase that attempt count or prematurely resolve an existing incident. It
parses the creation timestamp from the filename, rather than trusting the
upload date: migrating an old archive does not make it fresh. It compares
the remote size, SHA metadata and payload ETag with the local archive. Hashes
are cached against inode/size/mtime, so each new archive is hashed once, not
every poll. No dumps are downloaded and no S3/database credentials leave the
production backup container. A failed S3 request is reported as unknown,
separately from a confirmed missing/stale backup. Freshness limit: 26 hours.

## Resource and isolation settings

`config/monitoring/umc-external-monitor.service` specifies:

- `MemoryMax=512M`, `MemoryHigh=384M`, `CPUQuota=25%` (0.25 CPU), `TasksMax=32`;
- a dynamic unprivileged user, private temporary directory and read-only
  system/home protection;
- retry startup every 30 seconds without a finite restart budget, so a long
  Telegram/network outage cannot leave the monitor permanently stopped;
- credentials in systemd's private credential directory, with source files
  readable only by root; incident state in the monitor's private StateDirectory;
- lower CPU priority and a higher OOM kill score than normal projects, to
  avoid preferentially sacrificing existing video workers under pressure.

The RAM value is a ceiling, not an allocation or a guarantee about the whole
host. Audit found a video worker peak around 5.2 GiB with a 7 GiB limit on the
8 GB VPS. Check actual monitor consumption after activation. Do not change
the existing worker's settings as part of this deployment.

## Staged installation

Use reviewed source merged to main. Copy only the two standalone scripts to
an immutable release directory under `/opt/umc-external-monitor/releases/`,
with a `current` symlink. Keep configuration under `/etc/umc-external-monitor/`.
Do not use the dirty production checkout as a build/source context.

1. Copy `external-monitor.example.json` to `config.json`. Set the actual
   channel/supergroup numeric ID and the dedicated bot's `bot_username`.
   Initially leave `snapshot` null. Keep credentials out of this JSON file.
2. Run the script with `--config ... --check`. This performs read-only page
   checks and sends neither Telegram messages nor watchdog pings.
3. The owner enters the dedicated token directly into the VPS console:

   ```sh
   python3 /opt/umc-external-monitor/current/external_monitor.py \
     --config /etc/umc-external-monitor/config.json --configure-token
   ```

   Input is hidden. The helper verifies the bot identity, destination type and
   publication rights before creating `telegram-token` with mode 0600. It
   refuses to overwrite an existing credential. Never paste tokens into chat,
   shell command arguments or Git. Do not reset or reuse the application's bot.
4. Install the unit. Validate it with `systemd-analyze verify`, reload systemd
   metadata and enable/start **only** `umc-external-monitor.service`. A
   daemon-reload does not restart other projects. Check actual MemoryMax,
   CPUQuotaPerSecUSec, MemoryCurrent, logs and public probes after activation.
5. If agreed with the channel owner, send one clearly labelled technical
   test notification to `Server Alerts`. Do not inject production failures.

## Optional least-privilege reporter access

This requires a separate explicit access grant before activation. Generate a
new key on the monitoring VPS; never copy a developer's existing private key.
Its production `authorized_keys` entry must have `restrict`, the VPS source IP,
and a fixed `command` running the reviewed `monitor_snapshot.py`. No shell,
PTY, port forwarding, agent forwarding or caller-controlled command is allowed.
The production `deploy` account already has Docker access; the restricted key
can only request the allowlisted health report. The script does not interpret
`SSH_ORIGINAL_COMMAND`, modify application data or invoke stop/start/restart.

Pin the already verified production host key in
`/etc/umc-external-monitor/known_hosts`. Keep StrictHostKeyChecking enabled.
Install the reporter under a separate operational directory owned by deploy,
not over existing operational scripts or Compose files.

Only after that grant, add `external-monitor-reporter.conf` as a unit drop-in
and set:

```json
{
  "snapshot": {
    "host": "31.59.106.143",
    "user": "deploy",
    "known_hosts": "/etc/umc-external-monitor/known_hosts"
  }
}
```

Run `--check` with the reporter credential available, then restart only the
monitor to apply its optional new input. Production apps, databases, nginx
and Docker do not require a restart or configuration replacement.

## Monitoring the monitor itself

The Timeweb monitor survives a production host/Docker failure. It cannot
notify anyone if the Timeweb VPS itself loses connectivity. For that case,
configure an independent hosted dead-man check (for example Healthchecks.io),
with its own Telegram integration and email recipients Kamil/Bulat.

The optional `external-monitor-watchdog.conf` loads a private `watchdog_url`
credential. Only HTTPS `hc-ping.com` URLs are accepted. The monitor pings it
approximately every minute after successful recipient validation and
with no pending delivery failure. Only a canonical check UUID URL and an
explicit `OK` response count as an accepted ping. A recovered, unconfirmed
incident clears its obsolete delivery retry instead of silencing the
heartbeat permanently. Set the external check to one minute plus one minute
grace. Missing pings cause alerts from the external service,
independently of both hosts and the dedicated monitor bot.

With that schedule, a VPS or monitor outage is expected to be detected
roughly 60–120 seconds after it starts, plus Healthchecks.io processing and
Telegram delivery time. This is a timing estimate, not a guaranteed SLA.
The alert means the heartbeat is absent: the host, monitor, network or alert
delivery chain may need attention. It does not prove that the VPS powered off.

Validate external down/recovery delivery using a separate clearly labelled
test check: seed a heartbeat, let it expire, then send another heartbeat.
Pause the test check afterward. Keep the real heartbeat and all existing
projects running during this test. Use Healthchecks.io's own Telegram bot
for external delivery; never share the UMC alert bot token with the provider.

Do not claim this final layer is active until the external account/check,
recipients and delivery have actually been configured and verified. No UMC
data or secrets are included in those empty heartbeat requests.

## Rollback

Disable/stop only `umc-external-monitor.service`, or return its `current`
symlink/config to the previous release and restart only this monitor. Revoke
only its dedicated reporter public-key line if the optional grant is removed.
Keep existing apps, alerts, databases, Docker and all volumes in place.
