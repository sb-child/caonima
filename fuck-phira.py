#!/usr/bin/env python3
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import json
import time
from typing import List
import psutil


PW_METADATA_BASE_CMD = ["pw-metadata", "-n", "settings", "0"]
# PHIRA_NAME = "PipeWire ALSA [phira-main]"
PHIRA_NAME = "phira-main"


class PipeWireMonitor(threading.Thread):
    def __init__(self, callback=None, on_stream_open=None, on_stream_close=None, on_sink_unavailable=None, on_sink_available=None):
        super().__init__(daemon=True)
        self.callback = callback
        self.on_stream_open = on_stream_open
        self.on_stream_close = on_stream_close
        self.on_sink_unavailable = on_sink_unavailable
        self.on_sink_available = on_sink_available
        self.stop_event = threading.Event()
        self._check_event = threading.Event()
        self._lock = threading.Lock()
        self._last_state_hash = None
        self._active_streams = {}
        self._last_physical_sinks = None
        self._worker_thread = threading.Thread(
            target=self._debounced_worker, daemon=True)
        self._worker_thread.start()

    def _debounced_worker(self):
        """消费者线程"""
        while not self.stop_event.is_set():
            if self._check_event.wait(timeout=1.0):
                self._check_event.clear()
                time.sleep(0.1)
                self._check_event.clear()
                if not self.stop_event.is_set():
                    self.do_check()

    def run(self):
        """生产者线程"""
        while not self.stop_event.is_set():
            process = None
            try:
                process = subprocess.Popen(
                    ['pw-mon'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True
                )
                self._check_event.set()
                for line in iter(process.stdout.readline, ''):  # type: ignore
                    if self.stop_event.is_set():
                        break
                    if line.strip():
                        self._check_event.set()
                process.stdout.close()  # type: ignore
                process.wait()
            except Exception:
                if process:
                    process.kill()
            if not self.stop_event.is_set():
                time.sleep(1.0)

    def do_check(self):
        try:
            result = subprocess.run(
                ['pw-dump'], capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
        except Exception:
            return
        default_sink_name = None
        for obj in data:
            is_metadata = obj.get("type") == "PipeWire:Interface:Metadata"
            is_default_namespace = obj.get("props", {}).get(
                "metadata.name") == "default"
            if is_metadata and is_default_namespace:
                for meta in obj.get("metadata", []):
                    if meta.get("key") == "default.audio.sink":
                        val = meta.get("value")
                        if isinstance(val, dict):
                            default_sink_name = val.get("name")
                        elif isinstance(val, str):
                            try:
                                default_sink_name = json.loads(val).get("name")
                            except json.JSONDecodeError:
                                pass
                if default_sink_name:
                    break
        target_node = None
        current_streams = {}
        current_physical_sinks = set()
        for obj in data:
            if obj.get("type") == "PipeWire:Interface:Node":
                info = obj.get("info", {})
                props = info.get("props", {})
                node_id = obj.get("id")
                if props.get("node.name") == default_sink_name:
                    target_node = obj
                if props.get("media.class") == "Audio/Sink":
                    node_name = props.get("node.name", "")
                    device_api = props.get("device.api", "")
                    is_physical_sink = (
                        device_api in ("alsa", "bluez5") or
                        node_name.startswith("alsa_output.") or
                        node_name.startswith("bluez_output.")
                    )
                    is_virtual = "loopback" in node_name.lower() or "dummy" in node_name.lower()
                    if is_physical_sink and not is_virtual:
                        current_physical_sinks.add((node_id, node_name))
                if props.get("media.class") == "Stream/Output/Audio":
                    app_name = props.get("application.name") or props.get(
                        "media.name") or props.get("node.name") or "Unknown"
                    fmt = "unknown"
                    rate = 0
                    quantum = 0
                    params = info.get("params", {})
                    enum_fmt = params.get("EnumFormat", [])
                    if enum_fmt and isinstance(enum_fmt, list):
                        fmt_obj = enum_fmt[0]
                        if isinstance(fmt_obj, dict):
                            val = fmt_obj.get("value", fmt_obj)
                            fmt = val.get("format", fmt)
                            rate = val.get("rate", rate)
                    lat_str = props.get("node.latency", "")
                    if "/" in lat_str:
                        q, r = lat_str.split("/", 1)
                        if q.isdigit():
                            quantum = int(q)
                        if r.isdigit() and rate == 0:
                            rate = int(r)
                    if rate == 0:
                        rate_str = props.get("node.rate", "")
                        if "/" in rate_str:
                            r_split = rate_str.split("/")[1]
                            if r_split.isdigit():
                                rate = int(r_split)
                    current_streams[node_id] = {
                        "id": node_id,
                        "name": app_name,
                        "rate": (fmt, quantum, rate)
                    }
        if target_node:
            raw_state = target_node.get("info", {}).get("state", "unknown")
            state = raw_state.lower()
            fmt = "unknown"
            rate = 0
            quantum = 0
            info = target_node.get("info", {})
            params = info.get("params", {})
            props = info.get("props", {})
            fmt_list = params.get("Format", [])
            if fmt_list:
                fmt_obj = fmt_list[0]
                if isinstance(fmt_obj, dict):
                    val = fmt_obj.get("value", fmt_obj)
                    fmt = val.get("format", fmt)
                    rate = val.get("rate", rate)
            lat_list = params.get("Latency", [])
            if lat_list:
                lat_obj = lat_list[0]
                if isinstance(lat_obj, dict):
                    val = lat_obj.get("value", lat_obj)
                    quantum = val.get("size", quantum)
                    if rate == 0:
                        rate = val.get("rate", rate)
            if quantum == 0 or rate == 0:
                lat_str = props.get("node.latency", "")
                if "/" in lat_str:
                    q, r = lat_str.split("/", 1)
                    if q.isdigit() and quantum == 0:
                        quantum = int(q)
                    if r.isdigit() and rate == 0:
                        rate = int(r)
            if rate == 0:
                rate_str = props.get("node.rate", "")
                if "/" in rate_str:
                    rate = int(rate_str.split("/")[1])
            rate_tuple = (fmt, quantum, rate)
            current_state_hash = (default_sink_name, state, rate_tuple)
            with self._lock:
                if current_state_hash != self._last_state_hash:
                    self._last_state_hash = current_state_hash
                    if self.callback:
                        self.callback(default_sink_name, state, rate_tuple)
        with self._lock:
            current_ids = set(current_streams.keys())
            previous_ids = set(self._active_streams.keys())
            added_ids = current_ids - previous_ids
            removed_ids = previous_ids - current_ids
            for sid in added_ids:
                if self.on_stream_open:
                    self.on_stream_open(current_streams[sid])
            for sid in removed_ids:
                if self.on_stream_close:
                    self.on_stream_close(self._active_streams[sid])
            self._active_streams = current_streams
            if self._last_physical_sinks is None:
                if len(current_physical_sinks) == 0 and self.on_sink_unavailable:
                    self.on_sink_unavailable()
                elif len(current_physical_sinks) > 0 and self.on_sink_available:
                    self.on_sink_available()
            elif current_physical_sinks != self._last_physical_sinks:
                if len(current_physical_sinks) == 0 and self.on_sink_unavailable:
                    self.on_sink_unavailable()
                elif self.on_sink_available:
                    self.on_sink_available()
            self._last_physical_sinks = current_physical_sinks

    def stop(self):
        self.stop_event.set()
        self._check_event.set()


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


def change_rate(sample_rate: int, quantum: int):
    cmds = build_commands(sample_rate, quantum)
    for cmd in cmds:
        rc = run_command(cmd, dry_run=False)
        if rc != 0:
            return rc
    return 0


PHIRA_CURRENT_ID = 0


def on_phira_stream_open():
    change_rate(384000, 128)


def on_phira_stream_close():
    change_rate(48000, 512)


def send_signal(conf_file: Path):
    print(f"send_signal: 加载配置文件: {conf_file}")
    try:
        with open(conf_file, 'r', encoding='utf-8') as f:
            raw_content = f.read()
        config = json.loads(raw_content)
        if not isinstance(config, list):
            raise ValueError("配置文件的根节点必须是一个 JSON 数组")
    except FileNotFoundError:
        print(f"send_signal: 找不到配置文件: {conf_file}")
        return False
    except json.JSONDecodeError as e:
        print(f"send_signal: JSON 格式解析失败: {e}")
        return False
    except Exception as e:
        print(f"send_signal: 加载配置文件时发生未知错误: {e}")
        return False
    print(f"send_signal: 发现 {len(config)} 个选择器")
    for index, selector in enumerate(config):
        desc = selector.get('desc', f'selector_{index}')
        target_name = selector.get('name')
        target_fullpath = selector.get('fullpath')
        signal_num = selector.get('signal')
        print(f"send_signal: 处理选择器: {index} - {desc}")
        if target_name is None and target_fullpath is None:
            print(f"send_signal: 跳过 {index} - {desc}: name 和 fullpath 均为 null")
            continue
        if signal_num is None:
            print(f"send_signal: 跳过 {index} - {desc}: 未配置 signal 字段")
            continue
        try:
            signal_num = int(signal_num)
        except ValueError:
            print(
                f"send_signal: 跳过 {index} - {desc}: 无效的 signal 值: {signal_num}")
            continue
        matched_any = False
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                p_info = proc.info
                p_name = p_info.get('name')
                p_exe = p_info.get('exe')
                p_pid = p_info.get('pid')
                name_match = (target_name is None) or (p_name == target_name)
                path_match = (target_fullpath is None) or (
                    p_exe == target_fullpath)
                if name_match and path_match:
                    matched_any = True
                    print(
                        f"send_signal: 命中 {index} - {desc}: 匹配程序: PID={p_pid}, 进程名={p_name}, 路径={p_exe}")
                    try:
                        proc.send_signal(signal_num)
                        print(
                            f"send_signal: {index} - {desc}: 已向 PID {p_pid} 发送信号 {signal_num}")
                    except psutil.AccessDenied:
                        print(
                            f"send_signal: {index} - {desc}: 权限不足, 无法向 PID {p_pid} 发送信号")
                    except psutil.NoSuchProcess:
                        print(
                            f"send_signal: {index} - {desc}: 进程 PID {p_pid} 已在尝试发送信号前终止")
                    except Exception as e:
                        print(f"send_signal: {index} - {desc}: 发送信号时发生异常: {e}")

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        if not matched_any:
            print("send_signal: 此选择器未匹配到任何活动进程")
    return True


def kill_program_on_sink_unavailable():
    home = Path.home()
    p = home / ".caonima" / "fuck-phira" / "kill_program_on_sink_unavailable.json"
    send_signal(p)
    pass


CURRENT_DIR = Path(__file__).parent.resolve()
AUDIO_FILE = CURRENT_DIR / "empty.wav"


def play_audio():
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        print(
            f"play_audio: 开始播放音频 (第 {attempt}/{max_retries} 次尝试)...", flush=True)
        try:
            subprocess.run(
                ["pw-play", str(AUDIO_FILE)],
                timeout=2.0,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            print(f"play_audio: 第 {attempt} 次尝试成功", flush=True)
            break
        except subprocess.TimeoutExpired:
            print(
                f"play_audio: 第 {attempt} 次尝试发生阻塞, 进程已强制终止", flush=True)
            if attempt < max_retries:
                print(f"等待 1.5 秒后进行下一次重试...", flush=True)
                time.sleep(1.5)
        except subprocess.CalledProcessError as e:
            print(
                f"play_audio: 第 {attempt} 次尝试播放失败 (退出码 {e.returncode})", flush=True)
            if attempt < max_retries:
                print(f"等待 1.5 秒后进行下一次重试...", flush=True)
                time.sleep(1.5)
        except Exception as e:
            print(f"play_audio: 执行 pw-play 时发生未知异常: {e}", flush=True)
            break
    else:
        print(
            f"play_audio: 连续 {max_retries} 次执行 pw-play 均未成功, 放弃", flush=True)


PLAY_AUDIO_TIMER = None

if __name__ == '__main__':
    def on_device(name, state, rate):
        fmt, quantum, sample_rate = rate
        # "running": "工作中"
        # "suspended": "待机"
        # "idle": "空闲"
        # "creating": "创建中"
        # "error": "错误"
        print(
            f"[主设备变更] {name} 状态: {state} 格式={fmt}, Quantum={quantum}, 采样率={sample_rate}")

    def handle_stream_open(stream):
        global PHIRA_CURRENT_ID
        fmt, quantum, sample_rate = stream["rate"]
        print(
            f"[+] 流开启 ID: {stream['id']:<4} 源: {stream['name']} (格式={fmt}, Quantum={quantum}, 采样率={sample_rate})")
        stream_name = str(stream['name'])
        stream_id = str(stream['id'])
        stream_sample_rate = int(sample_rate)
        if stream_name.find(PHIRA_NAME) != -1 and stream_sample_rate == 384000:
            PHIRA_CURRENT_ID = stream_id
            print(f"on_phira_stream_open(): PHIRA_CURRENT_ID = {stream_id}")
            on_phira_stream_open()

    def handle_stream_close(stream):
        global PHIRA_CURRENT_ID
        print(f"[-] 流关闭 ID: {stream['id']:<4} 源: {stream['name']}")
        stream_name = str(stream['name'])
        stream_id = str(stream['id'])
        if stream_name.find(PHIRA_NAME) != -1 and stream_id == PHIRA_CURRENT_ID:
            print(
                f"on_phira_stream_close(): PHIRA_CURRENT_ID = {stream_id}")
            on_phira_stream_close()
            print(
                f"on_phira_stream_close(): reset PHIRA_CURRENT_ID")
            PHIRA_CURRENT_ID = 0

    def on_sink_unavailable():
        global PLAY_AUDIO_TIMER
        print("[Sink] 没有物理 Sink 可用")
        if PLAY_AUDIO_TIMER is not None:
            PLAY_AUDIO_TIMER.cancel()
            print("[Sink] PLAY_AUDIO_TIMER 定时器已被取消")
        kill_program_on_sink_unavailable()

    def on_sink_available():
        global PLAY_AUDIO_TIMER
        print("[Sink] 有物理 Sink 可用")
        if PLAY_AUDIO_TIMER is not None:
            PLAY_AUDIO_TIMER.cancel()
            print("[Sink] PLAY_AUDIO_TIMER 定时器已重置为 5 秒")
        else:
            print("[Sink] PLAY_AUDIO_TIMER 启动 5 秒定时器")
        PLAY_AUDIO_TIMER = threading.Timer(5.0, play_audio)
        PLAY_AUDIO_TIMER.start()

    monitor = PipeWireMonitor(
        callback=on_device,
        on_stream_open=handle_stream_open,
        on_stream_close=handle_stream_close,
        on_sink_unavailable=on_sink_unavailable,
        on_sink_available=on_sink_available,
    )
    monitor.start()
    try:
        while True:
            time.sleep(86400)
    except KeyboardInterrupt:
        monitor.stop()
        monitor.join()
