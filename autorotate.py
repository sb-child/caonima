import sys
import subprocess
import glob
import os
from pydbus import SystemBus
from gi.repository import GLib

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


def load_stolen_envs():
    from pathlib import Path
    import json
    import os
    import time
    d = Path("/tmp/sbchild/caonima")
    d.mkdir()
    drop_point = d / "niri-env.json"
    for _ in range(10):
        if drop_point.exists():
            try:
                with open(drop_point, "r") as f:
                    stolen_envs = json.load(f)
                    if "NIRI_SOCKET" in stolen_envs and Path(stolen_envs["NIRI_SOCKET"]).exists():
                        for key, value in stolen_envs.items():
                            os.environ[key] = value
                        print("load_stolen_envs: 已写入环境变量")
                        return True
                    else:
                        raise "load_stolen_envs: NIRI_SOCKET 不存在"
            except Exception as e:
                print(f"load_stolen_envs: 读取失败: {e}")
        time.sleep(1)
    print("load_stolen_envs: 放弃读取")
    return False


def set_screen_transform(transform):
    env = os.environ
    cmd = ["niri", "msg", "output", OUTPUT_NAME, "transform", transform]
    print(f"执行旋转指令: {' '.join(cmd)}")
    try:
        subprocess.run(cmd, env=env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"设置屏幕旋转失败，退出码: {e.returncode}", file=sys.stderr)
    except FileNotFoundError:
        print("未找到 niri 命令，请确保 niri 可执行文件已在系统的 PATH 中。", file=sys.stderr)


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
