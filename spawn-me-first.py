#!/usr/bin/env python3
import os
import json
from pathlib import Path


def main():
    target_vars = ["WAYLAND_DISPLAY", "DISPLAY",
                   "XDG_CURRENT_DESKTOP", "XDG_SESSION_TYPE", "NIRI_SOCKET"]
    stolen_data = {}
    for var in target_vars:
        if var in os.environ:
            stolen_data[var] = os.environ[var]
    if "NIRI_SOCKET" in stolen_data and Path(stolen_data["NIRI_SOCKET"]).exists():
        print(f"NIRI_SOCKET={stolen_data["NIRI_SOCKET"]}")
    else:
        print(f"NIRI_SOCKET 不存在")
        return
    cache_dir = Path("/tmp/sbchild/caonima")
    cache_dir.mkdir(parents=True, exist_ok=True)
    drop_point = cache_dir / "niri-env.json"
    with open(drop_point, "w") as f:
        json.dump(stolen_data, f)
    print(f"偷来了 {drop_point}")


if __name__ == "__main__":
    main()
