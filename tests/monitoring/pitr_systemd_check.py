"""Exercise real systemd credential mounts using synthetic data only."""

import argparse
import json
import os
import pwd
import secrets
import shutil
import subprocess
import tempfile
from pathlib import Path

CHECK = """
import json,os,signal,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from pitr_receiver import PostgreSQL,private_pgpass
source=Path(os.environ['CREDENTIALS_DIRECTORY'])/'pgpass'
assert source.read_bytes()==b'127.0.0.1:16543:*:fixture:synthetic-only\\n'
runtime=Path(os.environ['RUNTIME_DIRECTORY'])
assert runtime.stat().st_mode & 0o777==0o700
connection={'pg_host':'127.0.0.1','pg_port':16543,'pg_user':'fixture'}
with private_pgpass(connection) as config:
    private=Path(config['private_pgpass'])
    assert private.parent.parent==runtime
    assert private.stat().st_mode & 0o777==0o600
    assert private.read_bytes()==source.read_bytes()
    assert PostgreSQL(config).environment()['PGPASSFILE']==str(private)
    if sys.argv[1]=='kill':os.kill(os.getpid(),signal.SIGKILL)
assert not private.exists()
print(json.dumps({'systemd_source_mode':oct(source.stat().st_mode & 0o777),
                 'client_copy_mode':'0o600','normal_cleanup':True}),flush=True)
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError("The synthetic systemd harness requires root")
    account = pwd.getpwnam(args.user)
    if account.pw_uid == 0:
        raise ValueError("Run the fixture as an unprivileged service user")
    repo = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(
        prefix="ugc-pitr-credential-fixture-", dir="/run"
    ) as directory:
        work = Path(directory)
        work.chmod(0o755)
        for name in ("pitr_receiver.py", "pitr_store.py"):
            shutil.copyfile(repo / "scripts" / name, work / name)
            (work / name).chmod(0o644)
        script = work / "check.py"
        script.write_text(CHECK)
        script.chmod(0o644)
        source = work / "synthetic.pgpass"
        descriptor = os.open(
            source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(descriptor, "wb") as output:
            output.write(b"127.0.0.1:16543:*:fixture:synthetic-only\n")
        for mode in ("normal", "kill"):
            unit = "ugc-pitr-credential-check-" + secrets.token_hex(8)
            properties = {
                "User": args.user,
                "Group": str(account.pw_gid),
                "RuntimeDirectory": unit,
                "RuntimeDirectoryMode": "0700",
                "LoadCredential": "pgpass:" + str(source),
                "ProtectSystem": "strict",
                "ProtectHome": "yes",
                "PrivateTmp": "yes",
                "PrivateDevices": "yes",
                "PrivateNetwork": "yes",
                "NoNewPrivileges": "yes",
                "RestrictAddressFamilies": "AF_UNIX",
                "MemoryMax": "64M",
                "MemorySwapMax": "0",
                "CPUQuota": "25%",
                "TasksMax": "16",
                "RuntimeMaxSec": "30s",
                "TimeoutStopSec": "5s",
                # The deliberate kill is a successful fixture outcome.
                "SuccessExitStatus": "SIGKILL",
            }
            command = [
                "systemd-run",
                "--quiet",
                "--wait",
                "--pipe",
                "--collect",
                "--unit=" + unit,
            ]
            command += [
                "--property=" + key + "=" + value
                for key, value in properties.items()
            ]
            try:
                result = subprocess.run(
                    command + ["/usr/bin/python3", "-Es", str(script), mode],
                    capture_output=True,
                    text=True,
                    timeout=45,
                )
                if result.returncode:
                    raise RuntimeError(
                        "Synthetic credential fixture failed: "
                        + result.stderr[-2000:]
                    )
                if mode == "normal":
                    print(json.dumps(json.loads(result.stdout)), flush=True)
                assert not Path("/run", unit).exists()
            finally:
                subprocess.run(
                    ["systemctl", "stop", unit + ".service"],
                    capture_output=True,
                    timeout=10,
                )
        print(
            json.dumps({"hard_kill_cleanup": True, "synthetic_data_only": True})
        )


if __name__ == "__main__":
    main()
