"""Enable Docker live restore atomically after validating merged settings."""

import argparse
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path


def validate(config_path, docker_binary):
    result = subprocess.run(
        [str(docker_binary), "--validate", "--config-file", str(config_path)],
        capture_output=True,
        timeout=15,
    )
    if result.returncode:
        raise RuntimeError("Merged Docker configuration failed validation")


def configure(config_path, docker_binary, daemon_pid):
    previous = config_path.read_bytes() if config_path.exists() else None
    settings = json.loads(previous or b"{}")
    if settings.get("live-restore") is True:
        validate(config_path, docker_binary)
        os.kill(daemon_pid, signal.SIGHUP)
        return False
    settings["live-restore"] = True
    descriptor, filename = tempfile.mkstemp(
        prefix=".live-restore-",
        suffix=".json",
        dir=config_path.parent,
    )
    pending = Path(filename)
    try:
        with os.fdopen(descriptor, "w") as target:
            json.dump(settings, target, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        validate(pending, docker_binary)
        current = config_path.read_bytes() if config_path.exists() else None
        if current != previous:
            raise RuntimeError("Docker configuration changed during validation")
        backup = config_path.with_name(
            config_path.name + ".before-live-restore"
        )
        if not backup.exists():
            descriptor = os.open(
                backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "wb") as original:
                original.write(previous or b"{}\n")
                original.flush()
                os.fsync(original.fileno())
        os.replace(pending, config_path)
        try:
            os.kill(daemon_pid, signal.SIGHUP)
        except OSError:
            if previous is None:
                config_path.unlink()
            else:
                descriptor, filename = tempfile.mkstemp(
                    prefix=".live-restore-rollback-",
                    dir=config_path.parent,
                )
                with os.fdopen(descriptor, "wb") as target:
                    target.write(previous)
                    target.flush()
                    os.fsync(target.fileno())
                os.replace(filename, config_path)
            raise
    finally:
        pending.unlink(missing_ok=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--docker-binary", type=Path, required=True)
    parser.add_argument("--daemon-pid", type=int, required=True)
    args = parser.parse_args()
    if args.daemon_pid < 2:
        parser.error("Expected the host Docker daemon PID")
    configure(args.config, args.docker_binary, args.daemon_pid)
    print("Docker live-restore settings validated and reload requested")


if __name__ == "__main__":
    main()
