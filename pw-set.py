#!/usr/bin/env python3
"""
设置 PipeWire 的采样率 (rate) 和 quantum 参数。
"""

import argparse
import shlex
import subprocess
import sys
from typing import List

PW_METADATA_BASE_CMD = ["pw-metadata", "-n", "settings", "0"]


def parse_arguments() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="配置 PipeWire 的时钟采样率与 Quantum 参数。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        "--rate", "-r",
        type=int,
        required=True,
        help="目标采样率 (例如: 44100)"
    )
    parser.add_argument(
        "--quantum", "-q",
        type=int,
        required=True,
        help="目标 quantum 大小 (例如: 32)"
    )
    parser.add_argument(
        "--dry-run", "-d",
        action="store_true",
        help="仅打印将要执行的命令，不实际执行"
    )
    return parser.parse_args()


def build_commands(rate: int, quantum: int) -> List[List[str]]:
    properties = {
        "clock.rate": rate,
        "clock.force-rate": rate,
        "clock.max-quantum": quantum,
        "clock.force-quantum": quantum,
        "clock.quantum": quantum,
    }

    cmds = []
    for key, value in properties.items():
        cmds.append(PW_METADATA_BASE_CMD + [key, str(value)])
    return cmds


def run_command(cmd: List[str], dry_run: bool = False) -> int:
    cmd_str = shlex.join(cmd)
    if dry_run:
        print(f"[dry-run] {cmd_str}")
        return 0
    print(f"执行: {cmd_str}")
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True
        )
        if completed.stdout:
            print(completed.stdout.strip())
        if completed.stderr:
            print(completed.stderr.strip(), file=sys.stderr)
        return 0

    except subprocess.CalledProcessError as e:
        print(f"命令执行失败, 返回非零退出码 {e.returncode}", file=sys.stderr)
        if e.stdout:
            print(e.stdout.strip())
        if e.stderr:
            print(e.stderr.strip(), file=sys.stderr)
        return e.returncode

    except FileNotFoundError:
        print("错误: 找不到命令 'pw-metadata'", file=sys.stderr)
        return 127


def main() -> int:
    args = parse_arguments()
    cmds = build_commands(args.rate, args.quantum)

    for cmd in cmds:
        rc = run_command(cmd, dry_run=args.dry_run)
        if rc != 0:
            sys.exit(rc)

    print("全部命令执行成功。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
