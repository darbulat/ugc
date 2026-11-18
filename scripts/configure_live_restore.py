"""Enable Docker live restore atomically after validating merged settings."""

import argparse
import json
import os
import signal
import subprocess
import tempfile
from pathlib import Path


def configure(config_path, docker_binary, daemon_pid):
    previous = config_path.read_bytes() if config_path.exists() else None
    settings = json.loads(previous or b"{}")
    if settings.get("live-restore") is True:
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
        result = subprocess.run(
            [str(docker_binary), "--validate", "--config-file", str(pending)],
            capture_output=True,
            timeout=15,
        )
        if result.returncode:
            raise RuntimeError("Merged Docker configuration failed validation")
        current = config_path.read_bytes() if config_path.exists() else None
        if current != previous:
            raise RuntimeError("Docker configuration changed during validation")
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
