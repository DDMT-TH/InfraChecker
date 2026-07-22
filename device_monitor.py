from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
import os
import platform
import socket
import subprocess
from dotenv import load_dotenv
import requests

# โหลดค่าคอนฟิก
load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_DEVICE_WEBHOOK_URL")
SERVER_NAME = os.getenv("SERVER_NAME", "UNKNOWN-SERVER")
RAW_DEVICES = os.getenv("NETWORK_DEVICES", "")

STATUS_FILE = "device_status.json"


def parse_devices(raw_string):
    """แปลงข้อมูลดิบจาก .env เป็นโครงสร้างข้อมูลที่ใช้งานง่าย"""
    devices = []
    clean_raw = raw_string.replace("\n", "").strip()
    if not clean_raw:
        return devices

    parts = clean_raw.split(",")
    for part in parts:
        if part.strip():
            sub_parts = part.split(":")
            if len(sub_parts) >= 3:
                devices.append(
                    {
                        "ip": sub_parts[0].strip(),
                        "port": int(sub_parts[1].strip()),
                        "name": ":".join(sub_parts[2:]).strip(),
                    }
                )
    return devices


def ping_fallback(ip):
    """ยิง Ping ตรวจสอบระดับ ICMP หาก TCP Socket ไม่ตอบสนอง"""
    is_windows = platform.system().lower() == "windows"
    # พารามิเตอร์นับจำนวน (-n / -c) และ timeout (-w ms / -W sec)
    param = "-n" if is_windows else "-c"
    timeout_param = "-w" if is_windows else "-W"
    timeout_val = "1000" if is_windows else "1"

    cmd = ["ping", param, "1", timeout_param, timeout_val, ip]

    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        return res.returncode == 0
    except Exception:
        return False


def check_device_connection(device):
    """เช็กสถานะอุปกรณ์ด้วย TCP Socket ก่อน ถ้าไม่ผ่านจะใช้ ICMP Ping ช่วยยืนยัน"""
    ip = device["ip"]
    port = device["port"]
    name = device["name"]

    is_online = False

    # Step 1: ลองเช็กผ่าน TCP Socket ก่อน
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            result = s.connect_ex((ip, port))
            if result == 0:
                is_online = True
    except Exception:
        is_online = False

    # Step 2: ถ้า TCP Socket ล้มเหลว (เช่น Error 10060, 10061) ให้ลองยิง Ping ดูว่าเครื่องเปิดอยู่ไหม
    if not is_online:
        is_online = ping_fallback(ip)

    status_str = "ONLINE 🟢" if is_online else "OFFLINE 🔴"
    print(f"Checked {name} ({ip}:{port}) - {status_str}")

    return ip, name, is_online


def load_previous_status():
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_current_status(status_dict):
    try:
        with open(STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(status_dict, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Failed to save device status file: {e}")


def send_discord_device_alert(title, description, color, fields=[]):
    if not DISCORD_WEBHOOK_URL:
        print("❌ Webhook URL missing.")
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "fields": fields
                + [
                    {
                        "name": "Monitor Server",
                        "value": SERVER_NAME,
                        "inline": True,
                    },
                    {"name": "Timestamp", "value": timestamp, "inline": True},
                ],
                "footer": {"text": "Network Infrastructure Monitor"},
            }
        ]
    }
    try:
        requests.post(
            DISCORD_WEBHOOK_URL,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            timeout=5,
        )
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")


def main():
    devices = parse_devices(RAW_DEVICES)
    if not devices:
        print(
            "❌ ไม่พบรายชื่ออุปกรณ์ใน .env (ตรวจสอบตัวแปร NETWORK_DEVICES)"
        )
        return

    total_devices = len(devices)
    prev_status = load_previous_status()
    current_status = {}

    print(
        f"กำลังเริ่มตรวจสอบ Switch และ Access Point จำนวน {total_devices} ตัวในผังระบบ..."
    )

    # 🏎️ ตรวจสอบสถานะแบบขนาน (Concurrent)
    with ThreadPoolExecutor(max_workers=30) as executor:
        results = list(executor.map(check_device_connection, devices))

    for ip, name, is_online in results:
        current_status[ip] = {
            "name": name,
            "status": "ONLINE" if is_online else "OFFLINE",
        }

    new_offline_alerts = []
    recovered_alerts = []
    current_all_online = True

    online_count = 0
    offline_count = 0
    offline_summary_list = []

    for device in devices:
        ip = device["ip"]
        name = device["name"]

        old_data = prev_status.get(ip, {"status": "ONLINE"})
        old_state = old_data.get("status", "ONLINE")
        new_state = current_status[ip]["status"]

        if new_state == "OFFLINE":
            current_all_online = False
            offline_count += 1
            offline_summary_list.append(f"❌ **{name}** ({ip})")
        else:
            online_count += 1

        # ตรวจจับการเปลี่ยนสถานะ (Real-time Alert)
        if old_state == "ONLINE" and new_state == "OFFLINE":
            new_offline_alerts.append(f"🔴 **{name}** ({ip})")
        elif old_state == "OFFLINE" and new_state == "ONLINE":
            recovered_alerts.append(f"🟢 **{name}** ({ip})")

    was_all_online_last_time = (
        all(data.get("status") == "ONLINE" for data in prev_status.values())
        if prev_status
        else True
    )
    current_time = datetime.now()

    # ==========================================
    # 🚨 PART 1: REAL-TIME ALERTS (แจ้งเตือนเมื่อเปลี่ยนสถานะ)
    # ==========================================

    # CASE 1: มีเครื่องดับใหม่
    if new_offline_alerts:
        title = "🚨 [INFRA ALERT] Network Device Offline!"
        desc = f"ตรวจพบอุปกรณ์เครือข่ายสูญหายการเชื่อมต่อจำนวน **{len(new_offline_alerts)} อุปกรณ์**"
        fields = [
            {
                "name": "⚠️ Device Down List",
                "value": "\n".join(new_offline_alerts),
                "inline": False,
            }
        ]
        send_discord_device_alert(title, desc, 15158332, fields)

    # CASE 2: มีเครื่องฟื้นกลับมา (แต่ระบบโดยรวมยังไม่ 100%)
    if recovered_alerts and not current_all_online:
        title = "🔄 [INFRA RECOVERY] Device Back Online"
        desc = f"อุปกรณ์จำนวน **{len(recovered_alerts)} ตัว** ได้รับการกู้คืนระบบเรียบร้อยแล้ว (ยังมีบางส่วนดับอยู่)"
        fields = [
            {
                "name": "✅ Recovered List",
                "value": "\n".join(recovered_alerts),
                "inline": False,
            }
        ]
        send_discord_device_alert(title, desc, 16776960, fields)

    # CASE 3: เพิ่งกู้คืนกลับมาครบ 100%
    if current_all_online and not was_all_online_last_time:
        title = "🟢 [INFRA RESOLVED] Network Fully Operational"
        desc = "✨ ยอดเยี่ยม! อุปกรณ์ Switch และ Access Point ทั้งหมดในผังระบบกลับมาออนไลน์ครบ 100% แล้ว"
        send_discord_device_alert(title, desc, 3066993)

    # ==========================================
    # 📊 PART 2: SCHEDULED DAILY REPORT (ส่งตอน 12:00 น.)
    # ==========================================
    # หมายเหตุ: ตั้งค่าให้ส่งในช่วงนาทีแรกของชั่วโมง 12 (12:00)
    if current_time.hour == 12 and current_time.minute == 0:
        title = "📊 [INFRA DAILY REPORT] Network Status Overview"

        if current_all_online:
            desc = f"✨ รายงานประจำวัน: ระบบทำงานปกติ 100%\nอุปกรณ์ทั้งหมด **{total_devices} ตัว** ออนไลน์ครบถ้วน"
            color = 3447003
            fields = []
        else:
            desc = f"⚠️ รายงานประจำวัน: ตรวจพบอุปกรณ์มีปัญหาในระบบ\nจากทั้งหมด **{total_devices} ตัว**"
            color = 15105570
            fields = [
                {
                    "name": "🚨 อุปกรณ์ที่กำลัง Offline อยู่",
                    "value": "\n".join(offline_summary_list),
                    "inline": False,
                }
            ]

        summary_fields = [
            {"name": "🟢 Online", "value": f"{online_count} ตัว", "inline": True},
            {"name": "🔴 Offline", "value": f"{offline_count} ตัว", "inline": True},
        ]

        send_discord_device_alert(title, desc, color, summary_fields + fields)
    else:
        if current_all_online and was_all_online_last_time:
            print(
                "🟢 System normal & Not report time. No alert sent to prevent spam."
            )

    save_current_status(current_status)


if __name__ == "__main__":
    main()