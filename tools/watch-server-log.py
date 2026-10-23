"""后台监听远端服务日志，把请求/错误实时落到本地文件（断线自动重连）。

用法：python tools/watch-server-log.py --host 43.173.99.241 --out .tmp-serverlog.txt
凭据从环境变量 VPS_PWD 读取，不写进文件。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import paramiko

RECONNECT_DELAY = 5


def stream_once(client, unit: str, handle) -> None:
    channel = client.get_transport().open_session()
    channel.exec_command(f"journalctl -u {unit} -f -n 0 --no-pager")
    while True:
        if channel.recv_ready():
            chunk = channel.recv(65536).decode("utf-8", "replace")
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                if (
                    "showId=" in line
                    or "PROTOCOL_ERROR" in line
                    or "RENT_REJECTED" in line
                    or "ERROR" in line
                    or "Traceback" in line
                    or " 500 " in line
                ):
                    handle.write(line + "\n")
        elif channel.exit_status_ready():
            return
        else:
            time.sleep(0.2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="root")
    parser.add_argument("--unit", default="pethunter")
    parser.add_argument("--out", default=".tmp-serverlog.txt")
    args = parser.parse_args()

    password = os.environ.get("VPS_PWD")
    if not password:
        print("VPS_PWD is required", file=sys.stderr)
        return 1

    with open(args.out, "a", encoding="utf-8", buffering=1) as handle:
        while True:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            try:
                client.connect(args.host, username=args.user, password=password,
                               timeout=20, look_for_keys=False, allow_agent=False,
                               banner_timeout=30, auth_timeout=30)
            except Exception as error:  # noqa: BLE001 - 网络问题重试即可
                handle.write(f"=== reconnect failed: {type(error).__name__} ===\n")
                time.sleep(RECONNECT_DELAY)
                continue
            handle.write(f"=== watch started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
            try:
                stream_once(client, args.unit, handle)
            except Exception as error:  # noqa: BLE001
                handle.write(f"=== stream dropped: {type(error).__name__} ===\n")
            finally:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(RECONNECT_DELAY)


if __name__ == "__main__":
    raise SystemExit(main())
