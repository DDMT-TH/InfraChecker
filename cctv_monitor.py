import socket
import requests
import json
import os
import ipaddress  # 👈 ใช้ไลบรารีนี้ปลอดภัยกว่าในการจัดการ IP
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# โหลดค่าคอนฟิก
load_dotenv()
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_CCTV_WEBHOOK_URL")
SERVER_NAME = os.getenv("SERVER_NAME", "UNKNOWN-SERVER")

CCTV_IP_START = os.getenv("CCTV_IP_START", "192.168.10.101")
CCTV_IP_END = os.getenv("CCTV_IP_END", "192.168.10.228")
CCTV_PORT = int(os.getenv("CCTV_PORT", 80))

STATUS_FILE = "cctv_status.json"

def generate_ip_range(start_ip, end_ip):
    """ใช้ ipaddress เพื่อรองรับการเจนข้าม Subnet ได้อย่างสมบูรณ์"""
    try:
        start = ipaddress.IPv4Address(start_ip)
        end = ipaddress.IPv4Address(end_ip)
        ips = []
        curr = start
        while curr <= end:
            ips.append(str(curr))
            curr += 1
        return ips
    except ValueError as e:
        print(f"❌ IP Address Format Error: {e}")
        return []

def check_cctv(ip):
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            result = s.connect_ex((ip, CCTV_PORT))
            return ip, (result == 0)
    except Exception:
        return ip, False

def load_previous_status():
    if not os.path.exists(STATUS_FILE):
        return {}
    try:
        with open(STATUS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_current_status(status_dict):
    try:
        with open(STATUS_FILE, "w") as f:
            json.dump(status_dict, f, indent=4)
    except Exception as e:
        print(f"Failed to save CCTV status file: {e}")

def send_discord_cctv_alert(title, description, color, fields=[]):
    if not DISCORD_WEBHOOK_URL:
        return
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "fields": fields + [
                {"name": "Monitor Server", "value": SERVER_NAME, "inline": True},
                {"name": "Timestamp", "value": timestamp, "inline": True}
            ],
            "footer": {"text": "CCTV Auto-Monitor System"}
        }]
    }
    try:
        requests.post(DISCORD_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=5)
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")

def main():
    target_ips = generate_ip_range(CCTV_IP_START, CCTV_IP_END)
    if not target_ips:
        print("❌ ไม่สามารถสร้างรายการ IP ได้ ตรวจสอบ CCTV_IP_START และ CCTV_IP_END")
        return
        
    total_cameras = len(target_ips)
    prev_status = load_previous_status()
    current_status = {}
    
    print(f"กำลังตรวจสอบสถานะกล้อง CCTV จำนวน {total_cameras} ตัว...")
    
    with ThreadPoolExecutor(max_workers=40) as executor:
        results = executor.map(check_cctv, target_ips)
    
    for ip, is_online in results:
        current_status[ip] = "ONLINE" if is_online else "OFFLINE"
        
    new_offline = []
    recovered = []
    current_all_online = True
    
    # ตัวแปรเก็บสถิติสำหรับ Daily Report
    online_count = 0
    offline_count = 0
    offline_summary_list = []
    
    for ip in target_ips:
        old = prev_status.get(ip, "ONLINE")
        new = current_status[ip]
        
        if new == "OFFLINE":
            current_all_online = False
            offline_count += 1
            offline_summary_list.append(f"❌ {ip}")
        else:
            online_count += 1
            
        if old == "ONLINE" and new == "OFFLINE":
            new_offline.append(ip)
        elif old == "OFFLINE" and new == "ONLINE":
            recovered.append(ip)

    was_all_online_last_time = all(status == "ONLINE" for status in prev_status.values()) if prev_status else True
    current_time = datetime.now()

    # ==========================================
    # 🚨 PART 1: REAL-TIME ALERTS
    # ==========================================
    if new_offline:
        title = "🚨 [CCTV ALERT] Camera Connection Lost!"
        desc = f"พบกล้อง CCTV หยุดการเชื่อมต่อจำนวน **{len(new_offline)} ตัว**"
        fields = [{"name": "🔴 กล้องที่ขาดการติดต่อ", "value": "\n".join(new_offline), "inline": False}]
        send_discord_cctv_alert(title, desc, 15158332, fields)

    if recovered and not current_all_online:
        title = "🔄 [CCTV RECOVERY] Some Cameras Back Online"
        desc = f"กล้อง CCTV จำนวน **{len(recovered)} ตัว** กลับมาเชื่อมต่อได้แล้ว (แต่ยังมีตัวอื่นดับอยู่)"
        fields = [{"name": "✅ กล้องที่ฟื้นตัว", "value": "\n".join(recovered), "inline": False}]
        send_discord_cctv_alert(title, desc, 16776960, fields)

    if current_all_online and not was_all_online_last_time:
        title = "🟢 [CCTV RESOLVED] All System Operational"
        desc = f"✨ ยินดีด้วย! กล้อง CCTV ทั้งหมด **{total_cameras} ตัว** กลับมาออนไลน์ครบ 100% แล้ว"
        send_discord_cctv_alert(title, desc, 3066993)

    # ==========================================
    # 📊 PART 2: SCHEDULED DAILY REPORT (ส่งทุกกรณีตอน 12:00)
    # ==========================================
    # ดักจับช่วงนาทีที่ 0 ถึง 4 (กรณีรันทุก 5 นาที จะทำงานรอบเดียวแน่นอน)
    if current_time.hour == 12 and 0 <= current_time.minute <= 4:
        title = "📊 [CCTV DAILY REPORT] Status Overview"
        
        if current_all_online:
            desc = f"✨ รายงานประจำวัน: กล้อง CCTV ทั้งหมด **{total_cameras} ตัว** ทำงานปกติ 100%"
            color = 3447003
            fields = []
        else:
            desc = f"⚠️ รายงานประจำวัน: ตรวจพบกล้องมีปัญหาในระบบ\nจากทั้งหมด **{total_cameras} ตัว**"
            color = 15105570
            # จำกัดการแสดงผลไม่ให้ข้อความยาวเกินลิมิตของ Discord (Embed value limit คือ 1024 ตัวอักษร)
            if len(offline_summary_list) > 20:
                truncated_list = offline_summary_list[:20] + [f"...และอีก {len(offline_summary_list) - 20} ตัว"]
            else:
                truncated_list = offline_summary_list
                
            fields = [{"name": "🚨 รายชื่อกล้องที่ Offline อยู่ ณ ขณะนี้", "value": "\n".join(truncated_list), "inline": False}]
            
        summary_fields = [
            {"name": "🟢 Online", "value": f"{online_count} ตัว", "inline": True},
            {"name": "🔴 Offline", "value": f"{offline_count} ตัว", "inline": True}
        ]
        send_discord_cctv_alert(title, desc, color, summary_fields + fields)
    else:
        if current_all_online and was_all_online_last_time and not new_offline:
            print("🟢 ทุกตัวปกติ และไม่ครบรอบส่ง Daily Report -> ไม่ส่งข้อความสแปม")

    save_current_status(current_status)

if __name__ == "__main__":
    main()