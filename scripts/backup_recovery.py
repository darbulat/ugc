"""Create and upload a public-key encrypted operational recovery bundle."""

import argparse
import fcntl
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from production_release import (
    checked,
    escape_interpolation,
    inspect,
    live_snapshot,
    open_lock,
)

UPLOADER = """
import datetime, json, os, pathlib, sys
import boto3
from botocore.config import Config

sys.path.insert(0, "/app/scripts")
from backup_db import _get_s3_config
from s3_verified import verified_upload

path = pathlib.Path(sys.argv[1])
key = "recovery/" + path.name
config = _get_s3_config()
if config is None:
    raise SystemExit("S3 backup configuration unavailable")
client = boto3.client(
    "s3",
    endpoint_url=config["endpoint_url"],
    aws_access_key_id=config["access_key"],
    aws_secret_access_key=config["secret_key"],
    config=Config(
        s3={"addressing_style": os.environ.get("S3_ADDRESSING_STYLE", "auto")},
        retries={"mode": "standard", "max_attempts": 3},
        connect_timeout=10,
        read_timeout=90,
    ),
)
objects = [
    item
    for page in client.get_paginator("list_objects_v2").paginate(
        Bucket=config["bucket"]
    )
    for item in page.get("Contents", [])
]
if sum(item["Size"] for item in objects) + path.stat().st_size > 10_000_000_000:
    raise SystemExit("Recovery bundle exceeds configured S3 capacity")
if not verified_upload(client, config["bucket"], key, path):
    raise SystemExit("Recovery bundle upload failed verification")
head = client.head_object(Bucket=config["bucket"], Key=key)
if head["ContentLength"] != path.stat().st_size:
    raise SystemExit("Recovery bundle size mismatch")
cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(
    days=7
)
old = [
    item["Key"]
    for item in objects
    if item["Key"].startswith("recovery/ugc-recovery-")
    and item["Key"].endswith(".tar.gz.age")
    and item["LastModified"] < cutoff
]
for old_key in old:
    client.delete_object(Bucket=config["bucket"], Key=old_key)
print(json.dumps({"key": key, "bytes": head["ContentLength"]}))
"""


def recovery_plan(snapshot, recipient):
    sources = [
        {"path": "/sources/project/" + name, "name": "project/" + name}
        for name in (
            ".env",
            "docker-compose.yml",
            "docker-compose.dev.yml",
            "nginx",
            "config",
        )
    ]
    sources += [
        {"path": "/sources/operations/" + name, "name": "operations/" + name}
        for name in (
            "production_release.py",
            "backup_recovery.py",
            "recovery_bundle.py",
            "run_recovery_backup.sh",
            "recipient.txt",
            "recovery-image-id",
            "snapshot-environment.json",
            "installed.json",
            "bin/age",
        )
    ]
    sources += [
        {"path": "/sources/backup/" + name, "name": "backup/" + name}
        for name in (
            "timeweb.json",
            "timeweb-compose.yml",
            "RECOVERY.md",
            "restore-manifest.json",
            "restore-image",
        )
    ]
    sources += [
        {"path": "/sources/order-images", "name": "order-images"},
        {"path": "/sources/certificates", "name": "certificates"},
        {"path": "/sources/docker", "name": "docker"},
        {
            "path": "/sources/current-release/source.tar.gz",
            "name": "source.tar.gz",
        },
        {
            "path": "/sources/current-release/manifest.json",
            "name": "release-manifest.json",
        },
    ]
    return {
        "age_binary": "/tools/age",
        "recipient": recipient,
        "sources": sources,
        "memory": {
            "configuration/compose.json": json.dumps(
                escape_interpolation(snapshot),
                indent=2,
            )
        },
    }


def create_local_bundle(output, image, age, recipient):
    names = checked(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            "label=com.docker.compose.project=ugc",
        ]
    ).split()
    containers = json.loads(checked(["docker", "inspect", *names]))
    plan = recovery_plan(live_snapshot(containers), recipient)
    images = {}
    for current in containers:
        identifier = current["Image"]
        if identifier not in images:
            details = inspect(identifier, "image")
            images[identifier] = {
                "tags": details.get("RepoTags"),
                "digests": details.get("RepoDigests"),
                "revision": (details["Config"].get("Labels") or {}).get(
                    "org.opencontainers.image.revision"
                ),
            }
    plan["memory"]["configuration/images.json"] = json.dumps(images, indent=2)
    command = [
        "docker",
        "run",
        "--rm",
        "--name",
        "ugc-recovery-" + output.stem,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "DAC_OVERRIDE",
        "--security-opt",
        "no-new-privileges",
        "-i",
    ]
    mounts = (
        ("bind", "/opt/myapp/ugc", "/sources/project"),
        ("bind", "/home/deploy/.config/ugc-backup", "/sources/backup"),
        ("bind", "/opt/myapp/ugc-ops", "/sources/operations"),
        ("bind", str(age.resolve()), "/tools/age"),
        ("bind", "/opt/myapp/ugc-releases/current", "/sources/current-release"),
        ("bind", "/etc/docker", "/sources/docker"),
        ("volume", "ugc_order_images", "/sources/order-images"),
        ("volume", "ugc_certbot_data", "/sources/certificates"),
    )
    for kind, source, target in mounts:
        command += [
            "--mount",
            f"type={kind},source={source},target={target},readonly",
        ]
    command += [image, "python", "/app/scripts/recovery_bundle.py"]
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as target:
            result = subprocess.run(
                command,
                input=json.dumps(plan).encode(),
                stdout=target,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        if result.returncode:
            raise RuntimeError("Encrypted recovery bundle creation failed")
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        subprocess.run(
            ["docker", "rm", "-f", "ugc-recovery-" + output.stem],
            capture_output=True,
            timeout=30,
        )


def upload_bundle(path):
    remote = "/tmp/" + path.name
    try:
        checked(["docker", "cp", str(path), "ugc-db_backup-1:" + remote])
        output = checked(
            [
                "docker",
                "exec",
                "ugc-db_backup-1",
                "python",
                "-c",
                UPLOADER,
                remote,
            ],
            timeout=300,
        )
        return json.loads(output.strip().splitlines()[-1])
    finally:
        checked(["docker", "exec", "ugc-db_backup-1", "rm", "-f", remote])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recipient", type=Path, required=True)
    parser.add_argument("--age", type=Path, required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    image = inspect(args.image, "image")
    recipient = args.recipient.read_text().strip()
    if not recipient.startswith("age1"):
        parser.error("Expected an age public recipient")
    args.output_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(args.output_directory, 0o700)
    with (
        open_lock("/tmp/ugc-production-deploy.lock") as deployment_lock,
        open_lock("/tmp/ugc-recovery-bundle.lock") as backup_lock,
    ):
        fcntl.flock(deployment_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(backup_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        output = args.output_directory / (
            "ugc-recovery-" + stamp + ".tar.gz.age"
        )
        create_local_bundle(output, image["Id"], args.age, recipient)
        result = upload_bundle(output)
        cutoff = time.time() - 7 * 86400
        for previous in args.output_directory.glob("ugc-recovery-*.tar.gz.age"):
            if previous.stat().st_mtime < cutoff:
                previous.unlink()
        print(json.dumps(result))


if __name__ == "__main__":
    main()
