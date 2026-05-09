#!/usr/bin/env python3
import os
import sys
import subprocess
from pathlib import Path

TEMPLATE_FILENAME = "cnm.service"

SERVICES_TO_DEPLOY = {
    "autorotate": "autorotate.py",
    # "fsk": "fuck-screen-keyboard.py"
}

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def run_command(cmd, desc):
    print(f"正在执行: {desc} ...", end=" ")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, text=True)
        print("执行成功")
    except subprocess.CalledProcessError as e:
        print(f"错误信息: {e.stderr.strip()}")
        sys.exit(1)


def main():
    current_dir = Path(__file__).parent.resolve()
    template_path = current_dir / "template" / TEMPLATE_FILENAME

    if not template_path.exists():
        print(f"找不到模板文件: {template_path}")
        sys.exit(1)

    with open(template_path, "r", encoding="utf-8") as f:
        template_content = f.read()

    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True)
    print(f"目标 Systemd 目录: {SYSTEMD_USER_DIR}")
    installed_services = []
    print("开始生成并安装服务文件...")
    for service_name, script_filename in SERVICES_TO_DEPLOY.items():
        script_path = current_dir / script_filename
        if not script_path.exists():
            print(f"警告: 找不到脚本 {script_filename}，已跳过 {service_name} 的部署。")
            continue
        script_path.chmod(0o755)
        service_content = template_content.format(
            name=service_name,
            script_path=str(script_path)
        )
        target_service_filename = f"caonima-{service_name}.service"
        target_service_file = SYSTEMD_USER_DIR / target_service_filename
        with open(target_service_file, "w", encoding="utf-8") as f:
            f.write(service_content)
        installed_services.append(target_service_filename)
        print(f"已生成: {target_service_file.name} (指向 -> {script_filename})")
    if not installed_services:
        print("没有成功生成任何服务，脚本退出。")
        sys.exit(1)
    run_command(["systemctl", "--user", "daemon-reload"], "重载守护进程")
    for service_file in installed_services:
        cmd = ["systemctl", "--user", "enable", "--now", service_file]
        run_command(cmd, f"启动 {service_file} 服务")


if __name__ == "__main__":
    main()
