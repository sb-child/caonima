#!/usr/bin/env python3
from pathlib import Path
import subprocess
import threading
import os
import re
import time

CURRENT_DIR = Path(__file__).parent.resolve()
AUDIO_FILE = CURRENT_DIR / "empty.wav"


def play_audio(mac):
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(f"[{mac}] 开始播放音频 (第 {attempt}/{max_retries} 次尝试)...", flush=True)
        try:
            subprocess.run(
                ["pw-play", str(AUDIO_FILE)],
                timeout=2.0,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"[{mac}] 第 {attempt} 次尝试成功", flush=True)
            break
        except subprocess.TimeoutExpired:
            print(
                f"[{mac}] 第 {attempt} 次尝试发生阻塞, 进程已强制终止", flush=True)
            if attempt < max_retries:
                print(f"[{mac}] 等待 1.5 秒后进行下一次重试...", flush=True)
                time.sleep(1.5)
        except subprocess.CalledProcessError as e:
            print(
                f"[{mac}] 第 {attempt} 次尝试播放失败 (退出码 {e.returncode})", flush=True)
            if attempt < max_retries:
                print(f"[{mac}] 等待 1.5 秒后进行下一次重试...", flush=True)
                time.sleep(1.5)
        except Exception as e:
            print(f"[{mac}] 执行 pw-play 时发生未知异常: {e}", flush=True)
            break
    else:
        print(
            f"[{mac}] 连续 {max_retries} 次执行 pw-play 均未成功, 放弃", flush=True)


class BluetoothWarmup:
    def __init__(self, mac):
        self.mac = mac.upper()
        self.timer = None
        self.is_connected = False

    def play_audio(self):
        play_audio(self.mac)

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
                print(f"耳机 {self.mac} 已在 5 秒内断开连接, 定时器")

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


class UniversalBluetoothWarmup:
    def __init__(self):
        self.timers = {}

    def is_audio_device(self, mac):
        """检查刚刚连接的蓝牙设备是否包含音频输出特性"""
        try:
            result = subprocess.run(
                ["bluetoothctl", "info", mac],
                capture_output=True,
                text=True,
                timeout=2.0
            )
            output = result.stdout
            if "Audio Sink" in output or "Headset" in output:
                return True
            if "Icon: audio" in output:
                return True
            if "0000110b-0000-1000-8000-00805f9b34fb" in output.lower():  # A2DP UUID
                return True
        except Exception as e:
            print(f"[{mac}] 获取设备信息失败: {e}", flush=True)
        return False

    def play_audio(self, mac):
        play_audio(mac)

    def on_connected(self, mac):
        if mac in self.timers:
            self.timers[mac].cancel()
        if not self.is_audio_device(mac):
            print(f"[{mac}] 已连接, 但未检测到音频输出特性, 忽略这个设备", flush=True)
            return
        print(f"[{mac}] 检测到音频设备已连接, 启动 5 秒定时器", flush=True)
        timer = threading.Timer(5.0, self.play_audio, args=(mac,))
        self.timers[mac] = timer
        timer.start()

    def on_disconnected(self, mac):
        if mac in self.timers:
            self.timers[mac].cancel()
            del self.timers[mac]
            print(f"[{mac}] 耳机在 5 秒内断开连接, 定时器取消", flush=True)
        else:
            print(f"[{mac}] 已断开连接", flush=True)

    def start(self):
        print(f"开始监听蓝牙连接事件")
        process = subprocess.Popen(
            ["bluetoothctl"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )
        conn_pattern = re.compile(
            r"Device ([0-9A-F:]{17}) Connected: (yes|no)")
        try:
            for line in iter(process.stdout.readline, ''):  # type: ignore
                if not line:
                    break
                match = conn_pattern.search(line)
                if match:
                    mac = match.group(1)
                    status = match.group(2)
                    if status == "yes":
                        self.on_connected(mac)
                    else:
                        self.on_disconnected(mac)
        except KeyboardInterrupt:
            print("收到中断信号，正在退出监听...", flush=True)
        finally:
            for timer in self.timers.values():
                timer.cancel()
            process.terminate()


if __name__ == "__main__":
    univ = True
    mac_address = "80:C3:BA:91:0B:AB"
    print(f"univ = {univ}")
    print(f"mac_address = {mac_address}")
    print(f"CURRENT_DIR = {CURRENT_DIR}")
    print(f"AUDIO_FILE = {AUDIO_FILE}")
    if univ:
        monitor = UniversalBluetoothWarmup()
        monitor.start()
    else:
        monitor = BluetoothWarmup(mac_address)
        monitor.start()
