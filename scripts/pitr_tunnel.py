"""Loopback-only libpq relay over forced SSH commands, without forwarding."""

import argparse
import os
import signal
import socketserver
import subprocess
import threading
from pathlib import Path

from pitr_receiver import load_config, ssh_command, stop_child


class Relay(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, config):
        self.config = config
        self.children = set()
        self.lock = threading.Lock()
        self.capacity = threading.BoundedSemaphore(4)
        super().__init__(("127.0.0.1", 16543), Connection)

    def close_children(self):
        with self.lock:
            for process in list(self.children):
                stop_child(process)


class Connection(socketserver.BaseRequestHandler):
    def handle(self):
        server = self.server
        if not server.capacity.acquire(blocking=False):
            return
        process = None
        try:
            command = ssh_command(server.config) + [
                "deploy@" + server.config["ssh_host"],
                "ugc-pitr-db",
            ]
            with server.lock:
                process = subprocess.Popen(
                    command,
                    stdin=self.request,
                    stdout=self.request,
                    stderr=subprocess.DEVNULL,
                )
                server.children.add(process)
            process.wait()
        finally:
            if process:
                with server.lock:
                    server.children.discard(process)
            server.capacity.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    server = Relay(load_config(args.config))

    def stop(*args):
        server.close_children()
        os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with server:
        server.serve_forever()


if __name__ == "__main__":
    main()
