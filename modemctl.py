import os
import subprocess
import sys
import threading
import time
import shlex
import serial
from pathlib import Path
import logging

# 目标设备的 VID 和 PID (移远 RG200U/Rx500U 系列)
TARGET_VID = "2c7c"
TARGET_PID = "0900"
# 根据移远文档，AT 指令通信端口固定为接口 4 (去除前导零匹配 sysfs)
AT_INTERFACE_NUM = "4"
# 期望的最小速度 (5000 Mbps = SuperSpeed USB 3.0)
MIN_SPEED = 5000

g_module_ready = False
g_5g_dns_pri = ""
g_5g_dns_sec = ""


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] <%(threadName)s> %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout  # 强制输出到标准输出，方便 systemd 抓取
)


def send_at_command(port_path: str, command: str, timeout: float = 2.0):
    """
    向指定串口发送 AT 指令并阻塞读取完整返回值
    如果设备物理掉线，返回 None
    """
    if not os.path.exists(port_path):
        return None
    try:
        with serial.Serial(port_path, baudrate=115200, timeout=timeout, rtscts=False, dsrdtr=False) as ser:
            ser.reset_input_buffer()
            logging.info(f"发送: {command}")
            ser.write(f"{command}\r\n".encode('utf-8'))
            response_lines = []
            start_time = time.time()
            while (time.time() - start_time) < timeout:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    if line == command:
                        continue
                    logging.info(f"接收: {line}")
                    response_lines.append(line)
                    if line == "OK" or "ERROR" in line:
                        break
            return "\n".join(response_lines)
    except serial.SerialException as e:
        logging.error(f"串口通信异常(设备可能已拔出): {e}")
        return None
    except Exception as e:
        logging.error(f"未知错误: {e}")
        return None


def wait_module_quiet(port_path: str, quiet_time: float = 1.0, max_wait: float = 10.0) -> bool:
    """
    等待模块静默。如果中途设备掉线，返回 False。
    """
    logging.info(f"正在等待模块底层初始化广播结束...")
    if not os.path.exists(port_path):
        return False
    try:
        with serial.Serial(port_path, baudrate=115200, timeout=0.1, rtscts=False, dsrdtr=False) as ser:
            start_time = time.time()
            last_msg_time = time.time()
            while (time.time() - start_time) < max_wait:
                line = ser.readline().decode('utf-8', errors='ignore').strip()
                if line:
                    logging.info(f"  [开机广播] {line}")
                    last_msg_time = time.time()
                if (time.time() - last_msg_time) > quiet_time:
                    logging.info("模块已安静，缓冲区干干净净！\n")
                    return True
            logging.warning("等待广播结束超时，强行继续...")
            return True
    except serial.SerialException:
        logging.warning("监听广播时设备物理掉线！")
        return False
    except Exception:
        return False


def parse_qnetdevstatus(raw_output: str) -> dict:
    status_line = ""
    for line in raw_output.split('\n'):
        if "+QNETDEVSTATUS:" in line:
            status_line = line.strip()
            break
    if not status_line:
        return {}
    data_str = status_line.replace("+QNETDEVSTATUS:", "").strip()
    parts = data_str.split(',')
    network_info = {
        "ipv4":    parts[0] if len(parts) > 0 else "",
        "netmask": parts[1] if len(parts) > 1 else "",
        "gateway": parts[2] if len(parts) > 2 else "",
        "dhcp":    parts[3] if len(parts) > 3 else "",
        "dns_pri": parts[4] if len(parts) > 4 else "",
        "dns_sec": parts[5] if len(parts) > 5 else "",
    }
    return network_info


def send_notification(title, message, app_name="cnm-modemctl", icon="drive-removable-media", timeout=5000):
    real_user = os.environ.get("SUDO_USER") or os.getlogin()
    try:
        uid = subprocess.check_output(
            ["id", "-u", real_user], text=True).strip()
    except:
        uid = "1000"
    dbus_addr = f"unix:path=/run/user/{uid}/bus"
    cmd = [
        "sudo", "-u", real_user, f"DBUS_SESSION_BUS_ADDRESS={dbus_addr}",
        "gdbus", "call", "--session",
        "--dest", "org.freedesktop.Notifications",
        "--object-path", "/org/freedesktop/Notifications",
        "--method", "org.freedesktop.Notifications.Notify",
        app_name, "0", icon, title, message, "[]", "{}", str(timeout)
    ]
    safe_cmd = " ".join(shlex.quote(arg) for arg in cmd)
    try:
        subprocess.run(safe_cmd, shell=True, check=True,
                       capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        logging.error(f"[通知失败] 错误码: {e.returncode}\n错误输出: {e.stderr}")


def on_device_setup(serial_port: str):
    global g_5g_dns_pri, g_5g_dns_sec
    logging.info("on_device_unplug() serial: {serial_port}")
    send_notification(
        "5G模块已接入", f"串口设备: {serial_port}\n等待初始化...", icon="drive-removable-media")

    if not wait_module_quiet(serial_port, quiet_time=1.0):
        logging.warning("初始化期间设备丢失，提前终止流程。")
        return

    res = send_at_command(serial_port, "ATE0", timeout=1.0)
    if res is None:
        logging.warning("发送 ATE0 时设备丢失，提前终止流程。")
        return

    q = ""
    for i in range(10):
        q = send_at_command(serial_port, "AT+CSQ", timeout=1)

        if q is None:
            logging.warning("查信号时设备丢失，提前终止流程。")
            return

        logging.info(f"信号强度: {q}")
        if q and "+CSQ: 99,99" not in q and "ERROR" not in q:
            break
        time.sleep(1.0)

    if not q or "+CSQ: 99,99" in q:
        send_notification(
            "5G模块已接入", f"串口设备: {serial_port}\n设备无响应或无网络信号", icon="drive-removable-media")
        return
    else:
        clean_csq = [line for line in q.split('\n') if '+CSQ' in line]
        display_text = clean_csq[0] if clean_csq else q
        send_notification(
            "5G模块已接入", f"串口设备: {serial_port}\n信号状态: {display_text}", icon="drive-removable-media")

    network_info = {}
    for i in range(10):
        devstat = send_at_command(
            serial_port, "AT+QNETDEVSTATUS=1", timeout=1.0)

        if devstat is None:
            logging.warning("获取网络信息时设备丢失，提前终止流程。")
            return

        if "+QNETDEVSTATUS:" in devstat and "ERROR" not in devstat:
            network_info = parse_qnetdevstatus(devstat)
            break
        time.sleep(2.0)

    if network_info and network_info.get('ipv4'):
        logging.info(f"拨号成功: {network_info}")
        g_5g_dns_pri = network_info.get('dns_pri', '')
        g_5g_dns_sec = network_info.get('dns_sec', '')

        send_notification(
            "5G网络已就绪",
            f"IP: {network_info['ipv4']}\nDNS: {g_5g_dns_pri}",
            icon="network-transmit-receive"
        )
    else:
        send_notification("5G网络异常", "无法获取IP地址，请检查网络", icon="network-error")


def on_device_unplug():
    send_notification("5G模块已拔出", "", icon="drive-removable-media")
    logging.info("on_device_unplug()")
    global g_5g_dns_pri, g_5g_dns_sec
    # 设备拔出，清空全局 DNS
    g_5g_dns_pri = ""
    g_5g_dns_sec = ""


def detect_quectel_module():
    """
    静默扫描 USB 总线：
    - 如果发现目标模块且状态完好，返回映射的 tty 节点路径 (如 '/dev/ttyUSB6')
    - 如果未发现或状态不达标，返回 None
    """
    sysfs_usb_path = Path("/sys/bus/usb/devices")

    if not sysfs_usb_path.exists():
        logging.warning("detect_quectel_module(): sysfs_usb_path not exists")
        return None

    for dev_dir in sysfs_usb_path.iterdir():
        vid_file = dev_dir / "idVendor"
        pid_file = dev_dir / "idProduct"

        # 仅检查包含 VID/PID 文件的 USB 物理设备目录
        if not (vid_file.exists() and pid_file.exists()):
            continue

        try:
            vid = vid_file.read_text().strip()
            pid = pid_file.read_text().strip()
        except IOError:
            continue

        if vid == TARGET_VID and pid == TARGET_PID:
            logging.info(f"detect_quectel_module(): found {vid}:{pid}")
            # 1. 检查是否为 SuperSpeed (USB 3.0/3.1)
            speed_file = dev_dir / "speed"
            speed = 0
            if speed_file.exists():
                speed = int(speed_file.read_text().strip())
            logging.info(f"detect_quectel_module(): speed {speed}")
            if speed < MIN_SPEED:
                return None  # 速度不达标，跳过

            # 2. 查找 AT 指令接口 (Interface 4)
            at_interface_dir = None
            for iface_dir in dev_dir.glob(f"{dev_dir.name}:*.{AT_INTERFACE_NUM}"):
                at_interface_dir = iface_dir
                break
            logging.info(
                f"detect_quectel_module(): interface dir {at_interface_dir}")

            if not at_interface_dir:
                logging.warning(
                    f"detect_quectel_module(): cannot find interface {AT_INTERFACE_NUM}")
                return None  # 未枚举出接口 4，跳过

            # 3. 检查驱动是否加载并映射出 /dev/ttyUSBx
            tty_dirs = list(at_interface_dir.glob("ttyUSB*"))
            logging.info(
                f"detect_quectel_module(): checking {tty_dirs}")
            if not tty_dirs:
                tty_dirs = list(at_interface_dir.glob("tty/ttyUSB*"))
                logging.info(
                    f"detect_quectel_module(): checking {tty_dirs}")

            if tty_dirs:
                # 成功找到，返回绝对路径
                logging.info(
                    f"detect_quectel_module(): found /dev/{tty_dirs[0].name}")
                return f"/dev/{tty_dirs[0].name}"

    # 遍历结束仍未返回，说明没找到
    return None


def is_resolv_conf_empty() -> bool:
    """检查 /etc/resolv.conf 除注释外是否为空"""
    try:
        with open('/etc/resolv.conf', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    return False
        return True
    except Exception:
        return True


def is_other_network_connected() -> bool:
    """检查系统是否有其他活动网络 (排除 5G 虚拟网卡)"""
    try:
        output = subprocess.check_output(
            ['nmcli', '-t', '-f', 'DEVICE,TYPE,STATE', 'dev'], text=True)
        for line in output.split('\n'):
            line = line.strip()
            if not line:
                continue
            parts = line.split(':')
            if len(parts) >= 3:
                dev, dev_type, state = parts[0], parts[1], parts[2]
                if state == 'connected':
                    if dev.startswith('enx') or dev.startswith('usb') or dev.startswith('wwan'):
                        continue
                    return True
        return False
    except Exception as e:
        logging.error(f"nmcli 检查网络状态失败: {e}")
        return False


def dns_monitor_worker():
    """后台独立线程：负责在无网且 resolv.conf 为空时注入 5G DNS"""
    global g_module_ready, g_5g_dns_pri, g_5g_dns_sec
    logging.info("DNS 监控线程已成功启动，开始轮询...")
    while True:
        time.sleep(1)
        if g_module_ready and g_5g_dns_pri:
            if is_resolv_conf_empty() and not is_other_network_connected():
                logging.info(f"检测到断网且 resolv.conf 为空，正在接管 DNS...")
                try:
                    with open('/etc/resolv.conf', 'w') as f:
                        f.write("# Generated by 5G Modem Monitor Daemon\n")
                        if g_5g_dns_pri:
                            f.write(f"nameserver {g_5g_dns_pri}\n")
                        if g_5g_dns_sec:
                            f.write(f"nameserver {g_5g_dns_sec}\n")
                    logging.info(
                        f"成功写入 5G DNS: {g_5g_dns_pri}, {g_5g_dns_sec}")
                    send_notification(
                        "已应用运营商DNS设置",
                        f"DNS1: {g_5g_dns_pri}\nDNS2: {g_5g_dns_sec}",
                        icon="network-transmit-receive"
                    )
                except Exception as e:
                    logging.error(f"覆写 resolv.conf 失败: {e}")


if __name__ == "__main__":
    # 强制要求 root 权限
    if os.geteuid() != 0:
        print("[!] 错误: 必须以 root 权限运行此脚本。")
        sys.exit(1)

    print("--- 🚀 移远 5G 模块监控 Daemon 已启动 ---")

    monitor_thread = threading.Thread(target=dns_monitor_worker, daemon=True)
    monitor_thread.start()

    # 状态锁：记录设备上一次是否在线
    device_was_ready = False

    while True:
        tty_port = detect_quectel_module()

        if tty_port and not device_was_ready:
            logging.info(f"状态变更: 发现 5G 模块已插入并就绪！")
            on_device_setup(tty_port)
            device_was_ready = True

        elif not tty_port and device_was_ready:
            logging.info("状态变更: 5G 模块已拔出或掉线，等待重新接入...")
            on_device_unplug()
            device_was_ready = False

        time.sleep(1)
