"""Deploy CI-built images using durable snapshots of live Compose settings."""

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path

PROJECT = "ugc"
PROJECT_DIRECTORY = "/opt/myapp/ugc"
RELEASE_ROOT = Path("/opt/myapp/ugc-releases")
PORTS = {
    "app": 9999,
    "app_2": 9999,
    "admin": 8001,
    "max_bot": 8003,
    "instagram_webhook": 8002,
}


def checked(command, *, environment=None, stdin=None, timeout=90):
    result = subprocess.run(
        command,
        env=environment,
        input=stdin,
        text=True,
        capture_output=True,
        timeout=timeout,
    )
    if result.returncode:
        raise RuntimeError(f"Operation failed for {command[0]}")
    return result.stdout


def inspect(name, kind="container"):
    return json.loads(checked(["docker", kind, "inspect", name]))[0]


def environment_of(container):
    return dict(item.split("=", 1) for item in container["Config"]["Env"])


def open_lock(path):
    """Use the existing lock inode even when it belongs to another operator."""
    try:
        descriptor = os.open(
            path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
    except FileExistsError:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    return os.fdopen(descriptor, "r")


def escape_interpolation(value):
    """Preserve literal dollars when a resolved config is read by Compose."""
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_interpolation(item) for item in value]
    if isinstance(value, dict):
        return {key: escape_interpolation(item) for key, item in value.items()}
    return value


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as out:
        json.dump(value, out, indent=2)
        out.write("\n")
        out.flush()
        os.fsync(out.fileno())
    sync_directory(path.parent)


def sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def compose_base():
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "--project-directory",
        PROJECT_DIRECTORY,
    ]


def compose_environment(settings):
    values = settings.get("environment", {})
    if isinstance(values, dict):
        return values
    environment = {}
    for item in values:
        key, separator, value = item.partition("=")
        environment[key] = value if separator else None
    return environment


def rollout_environment(model, service, files, live):
    """Resolve the placeholder scheme used by previous production rollouts."""
    placeholders = re.compile(r"(?<!\$)\$\{(UGC_ROLLOUT_[A-Z0-9_]+)[^}]*\}")
    references = {
        name
        for path in files
        for name in placeholders.findall(Path(path).read_text())
    }
    mapping = {}
    for key, value in compose_environment(model["services"][service]).items():
        for name in placeholders.findall(str(value or "")):
            if key not in live or (name in mapping and mapping[name] != key):
                raise RuntimeError("Ambiguous live environment placeholder")
            mapping[name] = key
    if mapping.keys() != references:
        raise RuntimeError("Unresolved live environment placeholders")
    return os.environ | {name: live[key] for name, key in mapping.items()}


def pin_runtime(settings, current):
    settings.pop("build", None)
    settings.pop("env_file", None)
    settings["image"] = current["Image"]
    settings["environment"] = environment_of(current)
    logging = current.get("HostConfig", {}).get("LogConfig")
    if logging and logging["Type"]:
        settings["logging"] = {"driver": logging["Type"]}
        if logging.get("Config"):
            settings["logging"]["options"] = logging["Config"]
    healthcheck = current["Config"].get("Healthcheck")
    if healthcheck:
        settings.setdefault("healthcheck", {})["test"] = healthcheck["Test"]
    else:
        settings.pop("healthcheck", None)
    for setting, field in (("command", "Cmd"), ("entrypoint", "Entrypoint")):
        if current["Config"][field] is None:
            settings.pop(setting, None)
        else:
            settings[setting] = current["Config"][field]
    return settings


def live_snapshot(containers):
    """Resolve each service with its live environment and immutable image."""
    combined = {"name": PROJECT, "services": {}}
    for current in containers:
        labels = current["Config"]["Labels"]
        if labels.get("com.docker.compose.oneoff") == "True":
            continue
        service = labels["com.docker.compose.service"]
        files = labels["com.docker.compose.project.config_files"].split(",")
        command = compose_base()
        for filename in files:
            if not Path(filename).is_file():
                raise RuntimeError(f"Missing configuration for {service}")
            command += ["-f", filename]
        model = json.loads(
            checked(
                command + ["config", "--no-interpolate", "--format", "json"]
            )
        )
        environment = rollout_environment(
            model, service, files, environment_of(current)
        )
        resolved = unescape_interpolation(
            json.loads(
                checked(
                    command + ["config", "--format", "json"],
                    environment=environment,
                )
            )
        )
        settings = pin_runtime(resolved["services"][service], current)
        combined["services"][service] = settings
        for section in ("volumes", "networks", "configs", "secrets"):
            for name, item in resolved.get(section, {}).items():
                existing = combined.setdefault(section, {})
                if name in existing and existing[name] != item:
                    raise RuntimeError(f"Conflicting {section} configuration")
                existing[name] = item
    return combined


def verify_archive(directory):
    manifest = json.loads((directory / "manifest.json").read_text())
    if not re.fullmatch(r"[0-9a-f]{40}", manifest["revision"]):
        raise ValueError("Invalid release revision")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image_id"]):
        raise ValueError("Invalid release image ID")
    with (directory / "image.tar.gz").open("rb") as archive:
        digest = hashlib.file_digest(archive, "sha256").hexdigest()
    if digest != manifest["archive_sha256"]:
        raise ValueError("Release archive checksum mismatch")
    if "source_archive_sha256" in manifest:
        with (directory / "source.tar.gz").open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        if digest != manifest["source_archive_sha256"]:
            raise ValueError("Release source checksum mismatch")
    return manifest


def wait_ready(service, image_id, timeout=150):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = inspect(f"ugc-{service}-1")
        state = current["State"]
        if (
            current["Image"] == image_id
            and state["Status"] == "running"
            and state.get("Health", {}).get("Status") == "healthy"
        ):
            return
        time.sleep(2)
    raise RuntimeError(f"Readiness deadline exceeded for {service}")


def loaded_ci_image(directory, manifest):
    """Bind containerd manifest IDs to the checked CI configuration digest."""
    reference = manifest["registry_reference"]
    if reference != "ghcr.io/darbulat/ugc/app:" + manifest["revision"]:
        raise ValueError("Unexpected CI image reference")
    image = inspect(reference, "image")
    accepted = {manifest["image_id"]}
    if image["Id"] not in accepted:
        with tarfile.open(directory / "image.tar.gz", "r:gz") as archive:
            index = json.load(archive.extractfile("index.json"))
            for descriptor in index["manifests"]:
                digest = descriptor["digest"]
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                    raise ValueError("Invalid exported image digest")
                payload = archive.extractfile(
                    "blobs/sha256/" + digest.split(":")[1]
                ).read()
                if "sha256:" + hashlib.sha256(payload).hexdigest() != digest:
                    raise ValueError(
                        "Exported image manifest checksum mismatch"
                    )
                details = json.loads(payload)
                if (
                    details.get("config", {}).get("digest")
                    != manifest["image_id"]
                ):
                    continue
                config = archive.extractfile(
                    "blobs/sha256/" + manifest["image_id"].split(":")[1]
                ).read()
                if (
                    "sha256:" + hashlib.sha256(config).hexdigest()
                    != manifest["image_id"]
                ):
                    raise ValueError("Exported image config checksum mismatch")
                accepted.add(digest)
    if image["Id"] not in accepted:
        raise RuntimeError("Loaded image identity mismatch")
    if (image["Config"].get("Labels") or {}).get(
        "org.opencontainers.image.revision"
    ) != manifest["revision"]:
        raise RuntimeError("CI image revision mismatch")
    return image


def webhook_on_peer(service):
    """Keep the shared Telegram webhook registered during replacement."""
    program = """
import asyncio
from aiogram import Bot
from ugc_bot.config import load_config
from ugc_bot.telegram_webhook_app import _set_webhook_with_retry
async def main():
    config = load_config()
    expected = config.webhook.webhook_base_url.rstrip('/') + '/webhook/telegram'
    async with Bot(token=config.bot.bot_token) as bot:
        info = await bot.get_webhook_info()
        if not info.url:
            await _set_webhook_with_retry(
                bot, expected, config.webhook.webhook_secret.strip()
            )
            info = await bot.get_webhook_info()
        if info.url != expected:
            raise RuntimeError('Unexpected webhook configuration')
asyncio.run(asyncio.wait_for(main(), timeout=12))
"""
    checked(
        ["docker", "exec", "-i", f"ugc-{service}-1", "python", "-"],
        stdin=program,
        timeout=18,
    )


def reload_nginx():
    checked(["docker", "exec", "ugc-nginx-1", "nginx", "-t"])
    checked(["docker", "exec", "ugc-nginx-1", "nginx", "-s", "reload"])


def public_smoke():
    for path in ("/miniapp/app.html", "/admin/login"):
        status = checked(
            [
                "curl",
                "--silent",
                "--output",
                "/dev/null",
                "--max-time",
                "10",
                "--noproxy",
                "*",
                "--resolve",
                "bot.usemycontent.ru:443:127.0.0.1",
                "--write-out",
                "%{http_code}",
                "https://bot.usemycontent.ru" + path,
            ],
            timeout=15,
        )
        if status != "200":
            raise RuntimeError(f"Public smoke failed for {path}")


def write_snapshot(path, snapshot):
    content = json.dumps(escape_interpolation(snapshot))
    resolved = json.loads(
        checked(
            compose_base() + ["-f", "-", "config", "--format", "json"],
            stdin=content,
        )
    )
    normalized = normalized_services(resolved)
    if normalized != snapshot["services"]:
        differences = {
            service: sorted(
                key
                for key in settings.keys() | normalized.get(service, {}).keys()
                if settings.get(key) != normalized.get(service, {}).get(key)
            )
            for service, settings in snapshot["services"].items()
            if settings != normalized.get(service)
        }
        raise RuntimeError(
            "Durable configuration did not round-trip for " + str(differences)
        )
    private_json(path, escape_interpolation(snapshot))


def unescape_interpolation(value):
    """Decode the escaped dollar signs emitted by Compose config."""
    if isinstance(value, str):
        return value.replace("$$", "$")
    if isinstance(value, list):
        return [unescape_interpolation(item) for item in value]
    if isinstance(value, dict):
        return {
            key: unescape_interpolation(item) for key, item in value.items()
        }
    return value


def normalized_services(model):
    services = unescape_interpolation(model["services"])
    for settings in services.values():
        for key in ("command", "entrypoint"):
            if settings.get(key) is None:
                settings.pop(key, None)
    return services


def runtime_signature(container):
    config = container["Config"]
    host = container["HostConfig"]
    return {
        "environment": environment_of(container),
        "config": {
            key: config.get(key)
            for key in (
                "Cmd",
                "Entrypoint",
                "User",
                "WorkingDir",
                "StopSignal",
            )
        },
        "host": {
            key: host.get(key)
            for key in (
                "NetworkMode",
                "PortBindings",
                "RestartPolicy",
                "Privileged",
                "ReadonlyRootfs",
                "CapAdd",
                "CapDrop",
                "SecurityOpt",
                "Memory",
                "MemoryReservation",
                "MemorySwap",
                "NanoCpus",
                "CpuQuota",
                "CpuPeriod",
                "PidsLimit",
                "Ulimits",
                "LogConfig",
            )
        },
        "mounts": sorted(
            (item["Type"], item["Source"], item["Destination"], item["RW"])
            for item in container["Mounts"]
        ),
        "networks": sorted(container["NetworkSettings"]["Networks"]),
    }


def deploy_services(directory, services, previous, image_id):
    new_config = directory / "compose.json"
    command = ["up", "-d", "--no-deps", "--no-build", "--pull", "never"]
    attempted = []
    try:
        for service in services:
            peer = {"app": "app_2", "app_2": "app"}.get(service)
            current = inspect(f"ugc-{service}-1")
            if current["Id"] != previous[service]["container_id"]:
                raise RuntimeError(
                    f"Concurrent deployment detected for {service}"
                )
            if peer:
                other = inspect(f"ugc-{peer}-1")
                wait_ready(peer, other["Image"])
            attempted.append(service)
            print(f"Updating {service}", flush=True)
            checked(
                compose_base() + ["-f", str(new_config)] + command + [service],
                timeout=180,
            )
            if peer:
                webhook_on_peer(peer)
            wait_ready(service, image_id)
            updated = inspect(f"ugc-{service}-1")
            if runtime_signature(updated) != previous[service]["signature"]:
                raise RuntimeError(f"Runtime configuration drift for {service}")
            reload_nginx()
            public_smoke()
            print(f"Verified {service}", flush=True)
    except BaseException:
        if attempted:
            rollback_services(directory, attempted, previous)
        raise


def rollback_services(directory, services, previous):
    failures = []
    command = ["up", "-d", "--no-deps", "--no-build", "--pull", "never"]
    for service in reversed(services):
        try:
            checked(
                compose_base()
                + ["-f", str(directory / "previous-compose.json")]
                + command
                + [service],
                timeout=180,
            )
            wait_ready(service, previous[service]["image_id"])
            print(f"Restored previous image for {service}", flush=True)
        except Exception:
            failures.append(service)
    reload_nginx()
    for peer in ("app", "app_2"):
        if peer in services:
            webhook_on_peer(peer)
    if failures:
        raise RuntimeError(
            "Rollback requires attention for " + ", ".join(failures)
        )


def release(directory, services):
    manifest = verify_archive(directory)
    revision = manifest["revision"]
    revision_directory = RELEASE_ROOT / revision
    revision_directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(RELEASE_ROOT, 0o700)
    destination = Path(
        tempfile.mkdtemp(prefix="attempt-", dir=revision_directory)
    )
    if "source_archive_sha256" in manifest:
        descriptor = os.open(
            destination / "source.tar.gz",
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        with (
            (directory / "source.tar.gz").open("rb") as source,
            os.fdopen(descriptor, "wb") as target,
        ):
            shutil.copyfileobj(source, target)
            target.flush()
            os.fsync(target.fileno())
    with (directory / "image.tar.gz").open("rb") as archive:
        result = subprocess.run(
            ["docker", "image", "load"],
            stdin=archive,
            capture_output=True,
            timeout=300,
        )
    if result.returncode:
        raise RuntimeError("CI image could not be loaded")
    image = loaded_ci_image(directory, manifest)
    names = checked(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=" + PROJECT,
        ]
    ).split()
    containers = json.loads(checked(["docker", "container", "inspect", *names]))
    previous = {
        x["Config"]["Labels"]["com.docker.compose.service"]: {
            "image_id": x["Image"],
            "container_id": x["Id"],
            "signature": runtime_signature(x),
        }
        for x in containers
        if x["Config"]["Labels"].get("com.docker.compose.oneoff") != "True"
    }
    for service in services:
        wait_ready(service, previous[service]["image_id"])
    snapshot = live_snapshot(containers)
    write_snapshot(destination / "previous-compose.json", snapshot)
    candidate = copy.deepcopy(snapshot)
    for service in services:
        settings = candidate["services"][service]
        settings["image"] = image["Id"]
        settings["healthcheck"]["test"] = [
            "CMD",
            "python",
            "-c",
            "import urllib.request; "
            "urllib.request.urlopen("
            f"'http://localhost:{PORTS[service]}/ready', "
            "timeout=4)",
        ]
    write_snapshot(destination / "compose.json", candidate)
    inventory = {
        service: {key: item[key] for key in ("image_id", "container_id")}
        for service, item in previous.items()
    }
    private_json(
        destination / "manifest.json",
        manifest
        | {
            "services": services,
            "previous": inventory,
        },
    )
    public_smoke()
    deploy_services(destination, services, previous, image["Id"])
    private_json(
        destination / "verified.json",
        {"revision": revision, "verified_at": time.time()},
    )
    pending = RELEASE_ROOT / (".current-" + destination.name)
    pending.symlink_to(destination)
    os.replace(pending, RELEASE_ROOT / "current")
    sync_directory(RELEASE_ROOT)
    print(f"Release {revision} verified", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("services", nargs="+", choices=tuple(PORTS))
    args = parser.parse_args()
    if len(args.services) != len(set(args.services)):
        parser.error("Services must be unique")
    ordered = [service for service in PORTS if service in args.services]
    os.umask(0o077)
    with open_lock("/tmp/ugc-production-deploy.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        release(args.directory.resolve(strict=True), ordered)


if __name__ == "__main__":
    main()
