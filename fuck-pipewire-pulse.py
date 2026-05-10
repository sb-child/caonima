#!/usr/bin/env python3
from pathlib import Path
import subprocess
import threading
import os

MAC_ADDRESS = "80:C3:BA:91:0B:AB"
CURRENT_DIR = Path(__file__).parent.resolve()
AUDIO_FILE = CURRENT_DIR / "empty.wav"


class BluetoothWarmup:
    def __init__(self, mac):
        self.mac = mac.upper()
        self.timer = None
        self.is_connected = False

    def play_audio(self):
        print(f"耳机 {self.mac} 已稳定连接 5 秒, 开始播放 pw-play")
        try:
            subprocess.run(
                ["pw-play", AUDIO_FILE],
                timeout=2.0,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print("pw-play 播放完成")
        except subprocess.TimeoutExpired:
            print("pw-play 发生阻塞, 已强制终止进程")
        except Exception as e:
            print(f"执行 pw-play 时发生异常: {e}")

    def on_connected(self):
        if not self.is_connected:
            self.is_connected = True
            print(f"检测到耳机 {self.mac} 已连接, 启动 5 秒定时器")
            if self.timer is not None:
                self.timer.cancel()
            self.timer = threading.Timer(5.0, self.play_audio)
            self.timer.start()

    def on_disconnected(self):
        if self.is_connected:
            self.is_connected = False
            print(f"耳机 {self.mac} 已断开连接")
            if self.timer is not None:
                self.timer.cancel()
                print(f"耳机 {self.mac} 已在 5 秒内断开连接")

    def check_initial_status(self):
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", self.mac], capture_output=True, text=True)
            if "Connected: yes" in result.stdout:
                self.on_connected()
        except Exception:
            pass

    def start(self):
        print(f"开始监听 {self.mac} 的连接事件")
        self.check_initial_status()
        process = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        try:
            for line in iter(process.stdout.readline, ''):  # type: ignore
                if not line:
                    break
                if f"Device {self.mac} Connected: yes" in line:
                    self.on_connected()
                elif f"Device {self.mac} Connected: no" in line:
                    self.on_disconnected()
        except KeyboardInterrupt:
            print("收到中断信号，正在退出监听...")
        finally:
            if self.timer:
                self.timer.cancel()
            process.terminate()


if __name__ == "__main__":
    print(f"MAC_ADDRESS = {MAC_ADDRESS}")
    print(f"CURRENT_DIR = {CURRENT_DIR}")
    print(f"AUDIO_FILE = {AUDIO_FILE}")
    monitor = BluetoothWarmup(MAC_ADDRESS)
    monitor.start()
