import evdev
import subprocess
import asyncio
import sys

COMMAND_TO_EXECUTE = ["gdbus", "call", "--session", "--dest", "sm.puri.OSK0",
                      "--object-path", "/sm/puri/OSK0", "--method", "sm.puri.OSK0.SetVisible", "false"]


async def monitor_device(device):
    try:
        async for event in device.async_read_loop():
            if event.type == evdev.ecodes.EV_KEY:
                if event.value == 1:
                    key_event = evdev.categorize(event)
                    # print(f"[Evdev] 按键按下: {key_event.keycode}") # type: ignore
                    kcode: str | tuple = key_event.keycode  # type: ignore
                    trig = False
                    if isinstance(kcode, tuple) and len(kcode) > 0:
                        if str(kcode[0]).startswith("KEY_"):
                            trig = True
                    else:
                        if str(kcode).startswith("KEY_"):
                            trig = True
                    if trig:
                        subprocess.Popen(COMMAND_TO_EXECUTE)
    except OSError as e:
        print(f"设备已断开连接: {device.name}")


async def main():
    devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
    keyboard_devices = []
    for device in devices:
        capabilities = device.capabilities()
        if evdev.ecodes.EV_KEY in capabilities:
            keyboard_devices.append(device)
            print(f"成功挂载键盘设备: {device.name} (位于 {device.path})")
    if not keyboard_devices:
        print("警告：未找到任何键盘设备。请确保你使用了 sudo 运行脚本。")
        sys.exit(1)
    print("\n所有键盘设备已就绪，正在监听... (按 Ctrl+C 退出)")
    tasks = [monitor_device(dev) for dev in keyboard_devices]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序已优雅退出。")
