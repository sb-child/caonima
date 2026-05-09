#!/usr/bin/env python3
import sys
import subprocess
import glob
import os
from pydbus import SystemBus
from gi.repository import GLib, Gio
from pathlib import Path
import json
import time

OUTPUT_NAME = "eDP-1"

ORIENTATION_MAP = {
    "normal": "normal",
    "bottom-up": "180",
    "left-up": "90",
    "right-up": "270"
}

current_state = {
    "TabletMode": False,
    "Orientation": "normal"
}

DROP_POINT = Path("/tmp/sbchild/caonima/niri-env.json")
_env_monitor = None


def apply_env_file():
    if not DROP_POINT.exists():
        return False
    try:
        with open(DROP_POINT, "r") as f:
            stolen_envs = json.load(f)
        if "NIRI_SOCKET" in stolen_envs and Path(stolen_envs["NIRI_SOCKET"]).exists():
            for key, value in stolen_envs.items():
                os.environ[key] = value
            print(
                f"apply_env_file: 已写入环境变量 (NIRI_SOCKET={os.environ['NIRI_SOCKET']})")
            return True
        else:
            print("apply_env_file: 文件有效但 NIRI_SOCKET 不存在或路径失效")
            return False
    except Exception as e:
        print(f"apply_env_file: 读取失败: {e}")
        return False


def load_stolen_envs():
    for _ in range(10):
        if DROP_POINT.exists():
            if apply_env_file():
                return True
        time.sleep(1)
    print("load_stolen_envs: 放弃读取")
    return False


def setup_env_hot_reload():
    global _env_monitor
    DROP_POINT.parent.mkdir(parents=True, exist_ok=True)
    gfile = Gio.File.new_for_path(str(DROP_POINT))
    _env_monitor = gfile.monitor_file(Gio.FileMonitorFlags.NONE, None)

    def on_file_changed(monitor, file, other_file, event_type):
        if event_type in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            print(f"setup_env_hot_reload: {DROP_POINT.name} changed, applying")
            apply_env_file()
    _env_monitor.connect("changed", on_file_changed)
    print(f"setup_env_hot_reload: moniting {DROP_POINT.name}")


def set_screen_transform(transform):
    max_retries = 3
    retry_delay = 0.7
    for attempt in range(1, max_retries + 1):
        env = os.environ.copy()
        socket_path = env["NIRI_SOCKET"]
        if not socket_path:
            print(
                f"set_screen_transform: [tries {attempt}/{max_retries}] NIRI_SOCKET not found", file=sys.stderr)
            if attempt < max_retries:
                time.sleep(retry_delay)
                continue
            else:
                print(
                    "set_screen_transform: NIRI_SOCKET not found. give up.", file=sys.stderr)
                return
        cmd = ["niri", "msg", "output", OUTPUT_NAME, "transform", transform]
        try:
            subprocess.run(cmd, env=env, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(
                f"set_screen_transform: successfully set to {transform} (tried {attempt} times)")
            return

        except subprocess.CalledProcessError as e:
            print(
                f"set_screen_transform: [tries {attempt}/{max_retries}] niri returns: {e.returncode}, retrying", file=sys.stderr)
        except FileNotFoundError:
            print("set_screen_transform: niri command not found, give up.",
                  file=sys.stderr)
            return
        if attempt < max_retries:
            print(
                f"set_screen_transform: waiting {retry_delay} sec, attempt {attempt + 1}")
            time.sleep(retry_delay)
    print(f"set_screen_transform: give up.")


def apply_rotation_logic():
    if current_state["TabletMode"]:
        orientation = current_state["Orientation"]
        transform = ORIENTATION_MAP.get(orientation, "normal")
        set_screen_transform(transform)
    else:
        set_screen_transform("normal")


def on_properties_changed(interface_name, changed_properties, invalidated_properties):
    if interface_name != "org.sbchild.LaptopSensorDaemon":
        return

    need_update = False

    if "TabletMode" in changed_properties:
        current_state["TabletMode"] = changed_properties["TabletMode"]
        print(f"[事件] 平板模式状态变为: {current_state['TabletMode']}")
        need_update = True

    if "Orientation" in changed_properties:
        current_state["Orientation"] = changed_properties["Orientation"]
        print(f"[事件] 物理朝向变为: {current_state['Orientation']}")
        if current_state["TabletMode"]:
            need_update = True

    if need_update:
        apply_rotation_logic()


def main():
    bus = SystemBus()
    try:
        # https://github.com/sb-child/laptop-sensor-daemon
        proxy = bus.get("org.sbchild.LaptopSensorDaemon",
                        "/org/sbchild/LaptopSensorDaemon")
    except Exception as e:
        print(f"无法连接到系统守护进程，请确认 org.sbchild.LaptopSensorDaemon 是否在运行。错误: {e}")
        sys.exit(1)

    try:
        current_state["TabletMode"] = proxy.TabletMode
        current_state["Orientation"] = proxy.Orientation
        print(
            f"初始化状态: 平板模式={current_state['TabletMode']}, 朝向={current_state['Orientation']}")
        apply_rotation_logic()
    except Exception as e:
        print(f"读取初始传感器状态失败: {e}")

    proxy.PropertiesChanged.connect(on_properties_changed)

    print("正在监听硬件实时变更 (按 Ctrl+C 退出)...")
    loop = GLib.MainLoop()
    try:
        loop.run()
    except KeyboardInterrupt:
        print("\n收到退出信号，终止进程。")


if __name__ == "__main__":
    load_stolen_envs()
    main()
