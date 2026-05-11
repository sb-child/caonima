#!/usr/bin/env python3
import subprocess
import threading
import json
import re


class PipeWireMonitor(threading.Thread):
    def __init__(self, callback):
        """
        :param callback: 触发回调函数，签名需为 on_device(name, state, rate)
                         其中 rate 格式为 (format, quantum, rate)
        """
        super().__init__(daemon=True)
        self.callback = callback
        self.stop_event = threading.Event()
        self._debounce_timer = None
        self._lock = threading.Lock()
        self._last_state_hash = None

    def run(self):
        """线程主循环，负责监听并处理服务重启"""
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
            except Exception as e:
                if process:
                    process.kill()
            if not self.stop_event.is_set():
                self.stop_event.wait(1.0)

    def trigger_state_check(self):
        """防抖动触发器：PipeWire 状态切换瞬间会有大量事件爆发，防抖可以降低 CPU 开销"""
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(0.1, self.do_check)
            self._debounce_timer.start()

    def do_check(self):
        """执行 pw-dump 解析 JSON 提取目标数据"""
        try:
            result = subprocess.run(
                ['pw-dump'], capture_output=True, text=True, check=True)
            data = json.loads(result.stdout)
        except Exception:
            print("无法获取状态")
            return
        # print(f"data = {data}")
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
        if not default_sink_name:
            return
        target_node = None
        for obj in data:
            if obj.get("type") == "PipeWire:Interface:Node":
                if obj.get("info", {}).get("props", {}).get("node.name") == default_sink_name:
                    target_node = obj
                    break
        if not target_node:
            return
        raw_state = target_node.get("info", {}).get("state", "unknown")
        state = raw_state.lower()
        # state_map = {
        #     "running": "工作中",
        #     "suspended": "待机",
        #     "idle": "空闲",
        #     "creating": "创建中",
        #     "error": "错误"
        # }
        # state_cn = state_map.get(raw_state.lower(), raw_state)
        fmt = "未知"
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
        rate_tuple = (fmt, quantum, rate)  # quantum 是死的
        current_state_hash = (default_sink_name, state, rate_tuple)
        with self._lock:
            if current_state_hash != self._last_state_hash:
                self._last_state_hash = current_state_hash
                self.callback(default_sink_name, state, rate_tuple)

    def stop(self):
        """优雅关闭线程"""
        self.stop_event.set()
        if self._debounce_timer:
            self._debounce_timer.cancel()


if __name__ == '__main__':
    def on_device(name, state, rate):
        fmt, quantum, sample_rate = rate
        print(f"\n[设备变更] {name}")
        print(f" > 状态: {state}")
        print(f" > 规格: 格式={fmt}, Quantum={quantum}, 采样率={sample_rate}")
        print("-" * 50)
    monitor = PipeWireMonitor(callback=on_device)
    monitor.start()
    print("已启动 PipeWire 守护监听线程")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\n正在停止监听...")
        monitor.stop()
        monitor.join()
        print("已退出。")
