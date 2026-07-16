import os
import sys
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# 1. ตั้งค่าระบบ Logging เพื่อบันทึกประวัติการรันสคริปต์ลงไฟล์ (สำหรับงาน IT Infra)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("infra_monitor.log", encoding="utf-8"), # เซฟลงไฟล์
        logging.StreamHandler(sys.stdout) # แสดงผลบนหน้าจอ Terminal ด้วย
    ]
)

def run_script(script_name):
    """ฟังก์ชันสำหรับสั่งรันสคริปต์ Python ตัวอื่น ๆ และดักจับ Error"""
    logging.info(f"🚀 เริ่มต้นการทำงานของสคริปต์: {script_name}")
    try:
        # ใช้ os.system หรือการ import โมดูลเข้ามาสั่งรัน 
        # ในงาน Infra การใช้ os.system จะปลอดภัยที่สุดเพราะป้องกันตัวแปรหรือ Library ตีกันใน Memory
        exit_code = os.system(f"{sys.executable} {script_name}")
        
        if exit_code == 0:
            logging.info(f"✅ สคริปต์ {script_name} ทำงานเสร็จสิ้นอย่างสมบูรณ์")
        else:
            logging.error(f"❌ สคริปต์ {script_name} ทำงานล้มเหลว (Exit Code: {exit_code})")
            
    except Exception as e:
        logging.error(f"💥 เกิดข้อผิดพลาดในการรัน {script_name}: {str(e)}")

def main():
    start_time = datetime.now()
    logging.info("==================================================")
    logging.info("🏁 เริ่มต้นระบบตรวจสอบเครือข่ายและไอทีอินฟราสตรัคเจอร์")
    logging.info("==================================================")
    
    # รายชื่อไฟล์สคริปต์ทั้งหมดที่ต้องการรัน
    monitor_scripts = [
        "network_monitor.py",        # 1. ตรวจสอบเน็ตเวิร์กเซิร์ฟเวอร์ & อินเตอร์เน็ต
        "device_monitor.py", # 2. ตรวจสอบ Switch & AP ตามภาพแผนผัง
        "cctv_monitor.py"    # 3. ตรวจสอบกล้อง CCTV .101 ถึง .228
    ]
    
    # รันสคริปต์ทั้งหมดพร้อมกันแบบขนาน (Parallel Execution) เพื่อความรวดเร็วสูงสุด
    # โดยจะใช้เวลาทำงานรวมเท่ากับสคริปต์ตัวที่ทำงานช้าที่สุดเท่านั้น (ไม่เกิน 3 วินาที)
    with ThreadPoolExecutor(max_workers=len(monitor_scripts)) as executor:
        executor.map(run_script, monitor_scripts)
        
    end_time = datetime.now()
    duration = (end_time - start_time).total_seconds()
    logging.info(f"⏱️ ตรวจสอบระบบไอทีเสร็จสิ้นทั้งหมด ใช้เวลารวม: {duration:.2f} วินาที")
    logging.info("==================================================\n")

if __name__ == "__main__":
    main()