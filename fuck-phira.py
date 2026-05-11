#!/usr/bin/env python3
import shlex
import subprocess
import sys
import threading
import json
from typing import List


PW_METADATA_BASE_CMD = ["pw-metadata", "-n", "settings", "0"]
PHIRA_NAME = "PipeWire ALSA [phira-main]"


class PipeWireMonitor(threading.Thread):
    def __init__(self, callback, stream_callback=None):
        super().__init__(daemon=True)
        self.callback = callback
        self.stream_callback = stream_callback
        self.stop_event = threading.Event()
        self._debounce_timer = None
        self._lock = threading.Lock()
        self._last_state_hash = None
        self._last_streams_hash = None
        self._active_streams = {}

    def run(self):
        while not self.stop_event.is_set():
            process = None
            try:
                process = subprocess.Popen(
                    ['pw-mon'],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True
                )
                self.trigger_state_check()
                for line in iter(process.stdout.readline, ''):  # type: ignore
                    if self.stop_event.is_set():
                        break
                    if line.strip():
                        self.trigger_state_check()
                process.stdout.close()  # type: ignore
                process.wait()
            except Exception:
                if process:
                    process.kill()
            if not self.stop_event.is_set():
                self.stop_event.wait(1.0)

    def trigger_state_check(self):
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(0.1, self.do_check)
            self._debounce_timer.start()

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
        streams = []
        current_streams = {}

        for obj in data:
            if obj.get("type") == "PipeWire:Interface:Node":
                info = obj.get("info", {})
                props = info.get("props", {})
                node_id = obj.get("id")

                if props.get("node.name") == default_sink_name:
                    target_node = obj

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

                    # streams.append({
                    #     "name": app_name,
                    #     "rate": (fmt, quantum, rate)
                    # })
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

        if self.stream_callback:
            streams.sort(key=lambda x: x["name"])
            current_streams_hash = tuple(
                (s["name"], s["rate"]) for s in streams)
            with self._lock:
                if current_streams_hash != self._last_streams_hash:
                    self._last_streams_hash = current_streams_hash
                    self.stream_callback(streams)

    def stop(self):
        self.stop_event.set()
        if self._debounce_timer:
            self._debounce_timer.cancel()


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


PHIRA_LOCK = threading.Lock()


def on_phira_stream():
    pass


def on_phira_close():
    pass


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

    def on_streams(streams):
        print(f"[播放源更新] 当前活跃数量: {len(streams)}")
        for stream in streams:
            fmt, quantum, sample_rate = stream["rate"]
            name = stream["name"]
            print(f"源: {name} 格式={fmt}, Quantum={quantum}, 采样率={sample_rate}")

    monitor = PipeWireMonitor(callback=on_device, stream_callback=on_streams)
    monitor.start()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        monitor.stop()
        monitor.join()
