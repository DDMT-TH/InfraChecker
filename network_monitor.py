import socket
import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

# โหลดค่าจากไฟล์ .env ที่อยู่ในโฟลเดอร์เดียวกัน
load_dotenv()

# ดึงค่า Configuration มาจากไฟล์ .env (หากไม่มีค่าใน .env จะใช้ค่า Default ด้านหลัง)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_NETWORK_WEBHOOK_URL")
SERVER_NAME = os.getenv("SERVER_NAME", "UNKNOWN-SERVER")
LOCAL_GATEWAY = os.getenv("LOCAL_GATEWAY", "192.168.1.1")

STATUS_FILE = "network_status.txt"

# ตรวจสอบเบื้องต้นว่าใส่ Webhook URL หรือยัง
if not DISCORD_WEBHOOK_URL:
    print("❌ Error: ไม่พบค่า DISCORD_WEBHOOK_URL ในไฟล์ .env")
    exit(1)

def ping_port(host, port, timeout=2):
    """ตรวจเช็กพอร์ตปลายทางด้วย TCP Socket"""
    try:
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
        return True
    except (socket.timeout, socket.error):
        return False

def get_previous_status():
    """อ่านสถานะเดิมจากไฟล์"""
    if not os.path.exists(STATUS_FILE):
        return "NORMAL"
    try:
        with open(STATUS_FILE, "r") as f:
            return f.read().strip()
    except Exception:
        return "NORMAL"

def save_current_status(status):
    """บันทึกสถานะปัจจุบันลงไฟล์"""
    try:
        with open(STATUS_FILE, "w") as f:
            f.write(status)
    except Exception as e:
        print(f"Failed to save status file: {e}")

def send_discord_alert(status_type, title, description, color):
    """ส่งการแจ้งเตือนรูปแบบ Rich Embed ไปที่ Discord"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "embeds": [{
            "title": f"{status_type} {title}",
            "description": description,
            "color": color,
            "fields": [
                {"name": "Host/Server", "value": SERVER_NAME, "inline": True},
                {"name": "Timestamp", "value": timestamp, "inline": True}
            ],
            "footer": {"text": "IT Infra Auto-Monitor System"}
        }]
    }
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, data=json.dumps(payload), headers={"Content-Type": "application/json"}, timeout=5)
        if response.status_code != 204:
            print(f"Discord API error: {response.status_code}")
    except Exception as e:
        print(f"Failed to send Discord alert: {e}")

def run_network_audit():
    prev_status = get_previous_status()
    current_time = datetime.now()
    
    # 🌟 1. เช็ก Local Network
    gateway_port = 8443 
    gateway_ok = ping_port(LOCAL_GATEWAY, gateway_port, timeout=2)
    
    # 🌟 2. เช็ก Internet (ผ่านพอร์ต TCP 53 ของ Public DNS)
    public_dns_1 = "8.8.8.8"
    public_dns_2 = "1.1.1.1"
    internet_ok = ping_port(public_dns_1, 53) or ping_port(public_dns_2, 53)
    
    # --- ประเมินสถานะปัจจุบัน ---
    if not gateway_ok:
        current_status = "CRITICAL"
    elif not internet_ok:
        current_status = "WARNING"
    else:
        current_status = "NORMAL"

    # ==========================================
    # 🚨 PART 1: REAL-TIME ALERTS (ส่งเมื่อมีการเปลี่ยนสถานะ)
    # ==========================================
    if prev_status != current_status:
        if current_status == "CRITICAL":
            err_msg = f"ไม่สามารถเชื่อมต่อไปยัง Local Gateway ({LOCAL_GATEWAY}:{gateway_port}) ได้\nคาดว่ามีปัญหาที่สาย LAN, Switch หรือ Network Card (NIC)"
            send_discord_alert("🚨 [CRITICAL]", "Local Network Area Is Down!", err_msg, 15158332)
            
        elif current_status == "WARNING":
            err_msg = f"เชื่อมต่อเกตเวย์ ({LOCAL_GATEWAY}) ได้ แต่ไม่สามารถออกอินเตอร์เน็ตภายนอกได้\nโปรดตรวจสอบคู่สาย ISP, Router หรือ Firewall Rules"
            send_discord_alert("⚠️ [WARNING]", "Internet Connection Lost!", err_msg, 16776960)
            
        elif current_status == "NORMAL":
            success_msg = "ระบบเครือข่ายได้รับการแก้ไขและกลับมาใช้งานได้เป็นปกติแล้ว\nการเชื่อมต่อเสถียร 100%"
            send_discord_alert("🟢 [RECOVERY]", "Network Status: Resolved", success_msg, 3066993)
    else:
        if current_status == "NORMAL" and not (current_time.hour == 12 and current_time.minute == 0):
            print("🟢 System normal. Alert skipped to prevent spam.")

    # ==========================================
    # 📊 PART 2: SCHEDULED DAILY REPORT (ส่งทุกกรณีตอน 12:00 น.)
    # ==========================================
    # เช็กเจาะจงที่นาทีที่ 0 เพื่อป้องกันบอทส่งสแปมซ้ำซ้อน
    if current_time.hour == 12 and current_time.minute == 0:
        if current_status == "NORMAL":
            report_msg = "📊 รายงานประจำวัน: ระบบเครือข่ายปกติ 100%\nการเชื่อมต่อภายใน (Gateway) และภายนอก (Internet) ทำงานได้ดีเยี่ยม"
            send_discord_alert("📊 [DAILY REPORT]", "Network Status: OK", report_msg, 3447003)
        elif current_status == "WARNING":
            report_msg = f"⚠️ รายงานประจำวัน: ตรวจพบปัญหาอินเทอร์เน็ตล่มภายนอก\nสถานะปัจจุบันยังไม่สามารถออกนอกเครือข่ายได้ แต่อุปกรณ์ภายในปกติ"
            send_discord_alert("📊 [DAILY REPORT]", "Network Status: Internet Down", report_msg, 15105570)
        elif current_status == "CRITICAL":
            report_msg = f"🚨 รายงานประจำวัน: ระบบวิกฤต! เครือข่ายภายในล่ม\nสถานะปัจจุบันไม่สามารถติดต่อเกตเวย์ ({LOCAL_GATEWAY}) ได้"
            send_discord_alert("📊 [DAILY REPORT]", "Network Status: Local LAN Down", report_msg, 15158332)

    # บันทึกสถานะปัจจุบันไว้เทียบรอบหน้า
    save_current_status(current_status)

if __name__ == "__main__":
    run_network_audit()