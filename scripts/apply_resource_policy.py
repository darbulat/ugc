"""Plan live resource caps and rotate only the two healthy app replicas."""

import argparse
import copy
import fcntl
import hashlib
import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path

import production_release as release

MIB = 1024 * 1024
SERVICES = frozenset(
    [
        "app",
        "app_2",
        "admin",
        "max_bot",
        "instagram_webhook",
        "scheduler",
        "db_backup",
        "kafka_consumer",
        "outbox_processor",
        "instagram_stats_collector_scheduler",
        "instagram_stats_scheduler",
        "db",
        "redis",
        "kafka",
        "zookeeper",
        "pgbouncer",
        "nginx",
        "certbot",
    ]
)
RESOURCE_FIELDS = ("Memory", "MemorySwap", "NanoCpus", "PidsLimit")
SNAPSHOT_KEYS = frozenset(
    "META_TOKEN_MONITOR_" + suffix
    for suffix in ("IMAGE", "SETTINGS_DIR", "STATE_DIR", "UID", "GID")
)


def load_policy(path):
    policy = json.loads(path.read_text())
    if policy["version"] != 1 or set(policy["services"]) != SERVICES:
        raise ValueError("Unexpected policy version or service scope")
    if policy["logging"] != {
        "driver": "json-file",
        "options": {"max-size": "20m", "max-file": "5"},
    }:
        raise ValueError("Unexpected logging policy")
    if policy["minimum_host_reserve_mib"] < 3584:
        raise ValueError("Insufficient host reserve")
    if not 140 <= policy["peak_headroom_percent"] <= 300:
        raise ValueError("Insufficient peak headroom")
    for limits in policy["services"].values():
        for key in ("memory_mib", "cpus", "pids"):
            if not math.isfinite(limits[key]) or limits[key] <= 0:
                raise ValueError("Invalid resource limit")
        if limits["memory_mib"] % 1 or limits["pids"] % 1:
            raise ValueError("Memory and process limits must be integers")
    return policy


def inventory():
    names = release.checked(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=" + release.PROJECT,
        ]
    ).split()
    if not names:
        raise RuntimeError("No production containers found")
    containers = json.loads(
        release.checked(["docker", "container", "inspect", *names])
    )
    result = {}
    for current in containers:
        labels = current["Config"]["Labels"]
        if labels.get("com.docker.compose.oneoff") == "True":
            continue
        service = labels["com.docker.compose.service"]
        if service in result:
            raise RuntimeError("Ambiguous service: " + service)
        result[service] = current
    if not result.keys() >= SERVICES:
        raise RuntimeError("Missing policy services")
    return result


def cgroup_sample(current):
    pid = current["State"]["Pid"]
    entries = Path(f"/proc/{pid}/cgroup").read_text().splitlines()
    unified = [line[3:] for line in entries if line.startswith("0::/")]
    if len(unified) != 1:
        raise RuntimeError("A cgroup v2 host is required")
    root = Path("/sys/fs/cgroup")
    path = (root / unified[0].lstrip("/")).resolve(strict=True)
    if not path.is_relative_to(root):
        raise RuntimeError("Invalid cgroup path")
    values = {
        key: int((path / filename).read_text())
        for key, filename in (
            ("current", "memory.current"),
            ("peak", "memory.peak"),
            ("pids", "pids.current"),
        )
    }
    values["events"] = dict(
        line.split()
        for line in (path / "memory.events").read_text().splitlines()
    )
    return values


def healthy(current):
    state = current["State"]
    if (
        state["Status"] != "running"
        or state.get("OOMKilled")
        or state.get("Health", {}).get("Status", "healthy") != "healthy"
    ):
        raise RuntimeError("Service is not healthy")


def proposed_limits(current, limits):
    host = current["HostConfig"]
    if host.get("CpuQuota", 0) > 0:
        raise RuntimeError("Review legacy CPU quota before applying policy")
    proposed = {
        "Memory": int(limits["memory_mib"] * MIB),
        "NanoCpus": int(limits["cpus"] * 1_000_000_000),
        "PidsLimit": int(limits["pids"]),
    }
    for field in tuple(proposed):
        if (host.get(field) or 0) > 0:
            proposed[field] = min(proposed[field], host[field])
    # The audited production host has no swap. Never alter reservations.
    proposed["MemorySwap"] = proposed["Memory"]
    return proposed


def check_headroom(service, desired, sample, percent):
    peak = max(sample["peak"], sample["current"])
    if desired["Memory"] * 100 < peak * percent:
        raise RuntimeError("Insufficient memory headroom for " + service)
    if desired["PidsLimit"] < max(32, sample["pids"] * 2):
        raise RuntimeError("Insufficient process headroom for " + service)


def plan(policy, containers, host_memory, samples):
    result = {}
    for service, limits in policy["services"].items():
        current = containers[service]
        healthy(current)
        desired = proposed_limits(current, limits)
        check_headroom(
            service, desired, samples[service], policy["peak_headroom_percent"]
        )
        result[service] = desired
    reserve = policy["minimum_host_reserve_mib"] * MIB
    if sum(x["Memory"] for x in result.values()) + reserve > host_memory:
        raise RuntimeError("Policy exceeds host memory budget")
    return result


def update(identifier, limits):
    release.checked(
        [
            "docker",
            "update",
            "--memory",
            str(limits["Memory"]),
            "--memory-swap",
            str(limits["MemorySwap"]),
            "--cpus",
            str(limits["NanoCpus"] / 1_000_000_000),
            "--pids-limit",
            str(limits["PidsLimit"]),
            identifier,
        ]
    )


def rollback_limits(current, host_memory, host_cpus):
    host = current["HostConfig"]
    # Docker update --memory 0 / --cpus 0 does not clear an existing limit.
    # Restore formerly unlimited workloads to the physical host's capacity.
    memory = host.get("Memory") or host_memory
    swap = host.get("MemorySwap") or memory
    # With no host swap, equal combined/memory limits restore full capacity.
    # Some runc versions reject raising memory with MemorySwap=-1 together.
    if swap == -1:
        swap = memory
    return {
        "Memory": memory,
        "MemorySwap": swap,
        "NanoCpus": host.get("NanoCpus") or host_cpus * 1_000_000_000,
        "PidsLimit": host.get("PidsLimit") or -1,
    }


def verify_in_place(before, after, desired, sample):
    if any(
        before[key] != after[key] for key in ("Id", "Image", "RestartCount")
    ):
        raise RuntimeError("Container replaced or restarted")
    if before["State"]["StartedAt"] != after["State"]["StartedAt"]:
        raise RuntimeError("Container start time changed")
    healthy(after)
    expected = copy.deepcopy(before)
    expected["HostConfig"].update(desired)
    if release.runtime_signature(after) != release.runtime_signature(expected):
        raise RuntimeError("Unexpected runtime configuration drift")
    if cgroup_sample(after)["events"] != sample["events"]:
        raise RuntimeError("Memory pressure or OOM event during update")


def apply_limits(
    containers, desired, samples, host_memory, host_cpus, headroom_percent=140
):
    attempted = []
    try:
        for service, limits in desired.items():
            before = containers[service]
            now = release.inspect(before["Id"])
            verify_in_place(before, now, {}, samples[service])
            check_headroom(
                service, limits, cgroup_sample(now), headroom_percent
            )
            attempted.append(service)
            update(before["Id"], limits)
            time.sleep(2)
            verify_in_place(
                before, release.inspect(before["Id"]), limits, samples[service]
            )
            print("Verified live limits: " + service, flush=True)
        release.public_smoke()
        time.sleep(5)
        for service, limits in desired.items():
            before = containers[service]
            verify_in_place(
                before, release.inspect(before["Id"]), limits, samples[service]
            )
    except BaseException:
        failures = []
        for service in reversed(attempted):
            try:
                before = containers[service]
                restored = rollback_limits(before, host_memory, host_cpus)
                update(before["Id"], restored)
                actual = release.inspect(before["Id"])
                verify_in_place(before, actual, restored, cgroup_sample(actual))
            except Exception:
                failures.append(service)
        if failures:
            raise RuntimeError(
                "Resource rollback requires attention: " + ", ".join(failures)
            ) from None
        raise


def prepare_directory(snapshot):
    anchor = (release.RELEASE_ROOT / "current").resolve(strict=True)
    manifest = json.loads((anchor / "manifest.json").read_text())
    source = anchor / "source.tar.gz"
    with source.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest["source_archive_sha256"]:
        raise RuntimeError("Current source checksum mismatch")
    destination = Path(tempfile.mkdtemp(prefix="policy-", dir=anchor.parent))
    shutil.copyfile(source, destination / "source.tar.gz")
    os.chmod(destination / "source.tar.gz", 0o600)
    release.private_json(destination / "manifest.json", manifest)
    release.write_snapshot(destination / "previous-compose.json", snapshot)
    return destination


def rotate_replicas(directory, containers, snapshot, logging):
    candidate = copy.deepcopy(snapshot)
    previous = {}
    for service in ("app", "app_2"):
        current = containers[service]
        candidate["services"][service]["logging"] = logging
        expected = copy.deepcopy(current)
        expected["HostConfig"]["LogConfig"] = {
            "Type": logging["driver"],
            "Config": logging["options"],
        }
        previous[service] = {
            "container_id": current["Id"],
            "image_id": current["Image"],
            "signature": release.runtime_signature(expected),
        }
    release.write_snapshot(directory / "compose.json", candidate)
    # Each call pins its own image. The replicas may legitimately differ.
    for service in ("app", "app_2"):
        release.deploy_services(
            directory, [service], previous, containers[service]["Image"]
        )


def publish(directory, snapshot, policy, mode):
    if not (directory / "compose.json").exists():
        release.write_snapshot(directory / "compose.json", snapshot)
    saved = release.normalized_services(
        json.loads((directory / "compose.json").read_text())
    )
    if saved != snapshot["services"]:
        raise RuntimeError("Verified settings differ from prepared snapshot")
    pending = copy.deepcopy(snapshot)
    for service in SERVICES:
        pending["services"][service]["logging"] = policy["logging"]
    release.write_snapshot(directory / "pending-logging-compose.json", pending)
    release.private_json(
        directory / "policy-operation.json",
        {
            "mode": mode,
            "verified_at": time.time(),
            "tool_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "policy": policy,
            "pending_logging": [
                s
                for s in sorted(SERVICES)
                if snapshot["services"][s].get("logging") != policy["logging"]
            ],
        },
    )
    link = release.RELEASE_ROOT / (".current-" + directory.name)
    link.symlink_to(directory)
    os.replace(link, release.RELEASE_ROOT / "current")
    release.sync_directory(release.RELEASE_ROOT)


def execute(mode, policy):
    info = json.loads(release.checked(["docker", "info", "--format", "json"]))
    if info.get("SwapTotal", 0) or int(
        Path("/proc/meminfo").read_text().split("SwapTotal:")[1].split()[0]
    ):
        raise RuntimeError("Review swap policy on this host first")
    containers = inventory()
    samples = {s: cgroup_sample(containers[s]) for s in SERVICES}
    desired = plan(policy, containers, info["MemTotal"], samples)
    for service, limits in desired.items():
        print(
            json.dumps(
                {
                    "service": service,
                    "limits": limits,
                    "observed_peak_bytes": samples[service]["peak"],
                }
            ),
            flush=True,
        )
    if mode == "plan":
        return
    release.public_smoke()
    snapshot = release.live_snapshot(list(containers.values()))
    directory = prepare_directory(snapshot)
    if mode == "apply":
        candidate = copy.deepcopy(snapshot)
        for service, limits in desired.items():
            expected = copy.deepcopy(containers[service])
            expected["HostConfig"].update(limits)
            release.pin_resources(candidate["services"][service], expected)
        # Validate durable settings before changing any live limit.
        release.write_snapshot(directory / "compose.json", candidate)
        apply_limits(
            containers,
            desired,
            samples,
            info["MemTotal"],
            info["NCPU"],
            policy["peak_headroom_percent"],
        )
    else:
        for service in SERVICES:
            actual = containers[service]["HostConfig"]
            if any(actual.get(k) != v for k, v in desired[service].items()):
                raise RuntimeError("Apply resource stage before log rotation")
        rotate_replicas(directory, containers, snapshot, policy["logging"])
    current = inventory()
    verified = release.live_snapshot(list(current.values()))
    publish(directory, verified, policy, mode)
    print("Verified policy snapshot: " + str(directory), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "rotate"))
    parser.add_argument("--policy", required=True, type=Path)
    parser.add_argument("--snapshot-environment", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.snapshot_environment:
        values = json.loads(args.snapshot_environment.read_text())
        if not values.keys() <= SNAPSHOT_KEYS:
            raise ValueError("Unexpected snapshot environment key")
        os.environ.update(values)
    policy = load_policy(args.policy)
    with release.open_lock("/tmp/ugc-production-deploy.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(args.mode, policy)


if __name__ == "__main__":
    main()
