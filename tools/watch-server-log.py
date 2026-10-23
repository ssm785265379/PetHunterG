"""后台监听远端服务日志，把请求/错误实时落到本地文件。

用法：python tools/watch-server-log.py --host 43.173.99.241 --out .tmp-serverlog.txt
凭据从环境变量 VPS_PWD 读取，不写进文件。
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import paramiko


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

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(args.host, username=args.user, password=password,
                   timeout=25, look_for_keys=False, allow_agent=False)
    channel = client.get_transport().open_session()
    channel.exec_command(f"journalctl -u {args.unit} -f -n 0 --no-pager")

    with open(args.out, "a", encoding="utf-8", buffering=1) as handle:
        handle.write(f"\n=== watch started {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        while True:
            if channel.recv_ready():
                chunk = channel.recv(65536).decode("utf-8", "replace")
                for line in chunk.splitlines():
                    if not line.strip():
                        continue
                    # 只保留有价值的行：请求、响应、错误
                    if (
                        "showId=" in line
                        or "PROTOCOL_ERROR" in line
                        or "ERROR" in line
                        or "Traceback" in line
                        or " 500 " in line
                    ):
                        handle.write(line + "\n")
            elif channel.exit_status_ready():
                break
            else:
                time.sleep(0.2)


if __name__ == "__main__":
    raise SystemExit(main())
