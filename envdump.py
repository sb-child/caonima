#!/usr/bin/env python3
import sys
import json
import shlex
from pathlib import Path


def main():
    cache_dir = Path("/tmp/sbchild/caonima")
    drop_point = cache_dir / "niri-env.json"

    if not drop_point.exists():
        print(
            f"错误: 找不到环境缓存文件 {drop_point}，请先运行 spawn-me-first.py", file=sys.stderr)
        sys.exit(1)

    try:
        with open(drop_point, "r") as f:
            env_data = json.load(f)
    except json.JSONDecodeError:
        print(f"错误: 无法解析 {drop_point}，JSON 格式损坏", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"错误: 读取文件时发生异常: {e}", file=sys.stderr)
        sys.exit(1)

    if "NIRI_SOCKET" not in env_data:
        print("错误: JSON 数据中未找到 NIRI_SOCKET 记录", file=sys.stderr)
        sys.exit(1)

    niri_socket_path = Path(env_data["NIRI_SOCKET"])
    if not niri_socket_path.exists():
        print(
            f"错误: NIRI_SOCKET 指向的路径不存在 ({niri_socket_path})", file=sys.stderr)
        sys.exit(1)

    if not niri_socket_path.is_socket():
        print(
            f"警告: NIRI_SOCKET 指向的路径存在，但似乎不是一个套接字文件 ({niri_socket_path})", file=sys.stderr)
    for key, value in env_data.items():
        safe_value = shlex.quote(value)
        print(f"export {key}={safe_value}")


if __name__ == "__main__":
    main()
