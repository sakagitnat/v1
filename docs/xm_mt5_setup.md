# ตั้งค่าบอทเทรด XM (MetaTrader 5) บนคอมตัวเอง

บอทนี้ **แยกจากบอท Deriv ที่รันบน GitHub Actions โดยสิ้นเชิง** — คนละไฟล์
state, คนละ broker, คนละ safety gate ไม่กระทบกัน ทั้งสองรันคู่กันไปได้
ตลอด

บอทนี้ต้องรันบนคอมของคุณเอง (ไม่ใช่คลาวด์) เพราะไลบรารี `MetaTrader5`
ของ Python ใช้ได้เฉพาะ **Windows** และต้องมีโปรแกรม MT5 เปิดอยู่บนเครื่อง
เดียวกันเท่านั้น — เมื่อปิดคอม บอทก็หยุดทำงานไปด้วย (วิเคราะห์/เปิดออเดอร์
ใหม่ไม่ได้) แต่ position ที่เปิดไว้แล้วพร้อม Stop Loss/Take Profit ยัง
ปลอดภัยอยู่ เพราะ SL/TP ถูกเก็บและบังคับใช้ฝั่งเซิร์ฟเวอร์ของ XM เอง ไม่ใช่
ฝั่งคอมคุณ

---

## 1. ติดตั้ง MT5 terminal ของ XM

1. ไปที่เว็บ XM แล้วเปิดบัญชีเดโม (demo account) — เลือกแพลตฟอร์ม **MT5**
   ไม่ใช่ MT4
2. ดาวน์โหลดและติดตั้งโปรแกรม "MetaTrader 5" เวอร์ชันของ XM
   (ชื่อไฟล์มักเป็น `xmglobal5setup.exe` หรือคล้ายกัน)
3. หลังติดตั้ง เปิดโปรแกรม แล้วล็อกอินด้วยบัญชีเดโมที่ได้จากอีเมล XM
   — จะได้ 3 อย่างที่ต้องใช้ในขั้นต่อไป:
   - **Login** (ตัวเลขบัญชี)
   - **Password** (รหัสผ่านของบัญชีเทรด ไม่ใช่รหัสอีเมล)
   - **Server** (ดูได้ที่ XM Members Area → จัดการ → รายละเอียดการเข้าสู่ระบบ
     MetaTrader เช่น `XMGlobal-Demo` หรือ `XMGlobal-MT5 6` — ถ้าชื่อไม่มีคำว่า
     "Demo" บอทจะถาม MT5 เองหลังล็อกอินว่าเป็นบัญชีเดโมหรือไม่
     และปฏิเสธบัญชีจริงเพื่อความปลอดภัย)

เก็บ 3 อย่างนี้ไว้ **ห้ามใส่ลงในไฟล์โค้ดหรือ commit เข้า git เด็ดขาด**
— ขั้นถัดไปจะตั้งเป็น environment variable แทน

## 2. ติดตั้ง Python และไลบรารี

1. ติดตั้ง Python 3.11+ จาก [python.org](https://www.python.org/downloads/)
   (ตอนติดตั้งให้ติ๊ก "Add Python to PATH")
2. เปิด PowerShell หรือ Command Prompt แล้ว clone/pull รีโป `v1` มาไว้บน
   เครื่องนี้ (branch `claude/ai-trading-manager-deriv-pmay2v` หรือ
   branch ที่มีไฟล์พวกนี้)
3. ติดตั้ง dependency:

   ```powershell
   cd v1
   pip install -r requirements.txt
   pip install -r requirements-mt5.txt
   ```

   (`requirements-mt5.txt` มีแค่ไลบรารี `MetaTrader5` ซึ่งใช้ได้เฉพาะ
   Windows เท่านั้น ไม่ต้องติดตั้งไฟล์นี้บนเครื่องอื่น)

## 3. ตั้งค่า environment variables

ตั้งค่าเหล่านี้ (ตัวอย่างใช้ PowerShell — เปลี่ยนค่าตามบัญชีเดโมจริงของคุณ):

```powershell
setx MT5_LOGIN "12345678"
setx MT5_PASSWORD "รหัสผ่านบัญชีเทรดของคุณ"
setx MT5_SERVER "XMGlobal-Demo"
```

`setx` จะจำค่าไว้ถาวรในเครื่อง (ต้องเปิด PowerShell/Terminal ใหม่อีกครั้ง
ถึงจะเห็นผล) ไม่ต้องตั้งอะไรเพิ่มถ้าต้องการค่าพื้นฐาน — แต่ถ้าอยากปรับ
ความเสี่ยงหรือสัญลักษณ์ที่เทรด ตั้งเพิ่มได้:

| ตัวแปร | ค่าเริ่มต้น | ความหมาย |
|---|---|---|
| `MT5_INSTRUMENTS` | `XAUUSD` | สัญลักษณ์ที่จะเทรด (คั่นด้วย comma ได้หลายตัว) — บอทจะค้นหาชื่อจริงใน MT5 ให้เอง ถ้า XM ใช้ชื่อแบบมี suffix เช่น `XAUUSD.s` |
| `MT5_RISK_PER_TRADE` | `0.01` (1%) | ความเสี่ยงต่อออเดอร์ เทียบกับเงินทุนทั้งหมด |
| `MT5_MAX_OPEN_POSITIONS` | `3` | จำนวน position เปิดพร้อมกันสูงสุด |
| `MT5_STRATEGY` | `ema_crossover` | `ema_crossover` (ค่าเดิม) หรือ `mean_reversion` (สวนราคาที่หลุดแถบ Bollinger) — ยังไม่ผ่านการพิสูจน์ว่ามี edge ใช้เพื่อเก็บข้อมูลบนบัญชีเดโมเท่านั้น |
| `MT5_MAX_DAILY_LOSS_PCT` | `0.03` (3%) | ขาดทุนสะสมต่อวันถึงเท่านี้แล้วบอทจะหยุดเปิดออเดอร์ใหม่ (reset ทุกวัน) |

**ห้ามตั้ง `MT5_ALLOW_LIVE_TRADING=true`** เว้นแต่ตั้งใจเทรดเงินจริงจริง ๆ
— ถ้า `MT5_SERVER` ไม่มีคำว่า "Demo" และบัญชีที่ล็อกอินไม่ใช่บัญชีเดโม
(เช็กจาก `account_info().trade_mode`) และไม่ได้ตั้งค่านี้ไว้ บอทจะตัดการเชื่อมต่อ
และปฏิเสธทันทีเพื่อป้องกันความผิดพลาด

## 4. ทดสอบรันด้วยมือก่อน

เปิดโปรแกรม MT5 ของ XM ทิ้งไว้ (ต้องเปิดอยู่ตลอดเวลาที่บอทจะรัน) แล้วรัน:

```powershell
cd v1
python scripts\run_mt5_service.py
```

ควรเห็น log แบบ `Connected to MT5 account ... -- equity ...` ถ้าเชื่อม
ต่อสำเร็จ ถ้าเห็น `MT5 not reachable this run` แปลว่า MT5 terminal ยังไม่
เปิดหรือยังล็อกอินไม่สำเร็จ — เปิด/ล็อกอินให้เรียบร้อยแล้วรันซ้ำ

## 5. ตั้งให้รันอัตโนมัติด้วย Windows Task Scheduler

บอทนี้ถูกออกแบบให้รัน "ครั้งเดียวแล้วจบ" ไม่ใช่โปรแกรมที่ค้างรันตลอด —
ให้ Task Scheduler เป็นคนเรียกมันทุก ๆ 30-60 นาทีตอนที่คอมเปิดอยู่ (คล้าย
cron ของ GitHub Actions ที่ใช้กับบอท Deriv) วิธีนี้ทำให้ "บอทพักตามคอม
อัตโนมัติ" ได้โดยไม่ต้องเขียนโค้ดเพิ่มเลย — ปิดคอมแล้ว Task Scheduler ก็
ไม่ยิงงาน แค่นั้นเอง เปิดคอมกลับมาก็รันต่อตามปกติ

สร้าง task ด้วย `schtasks` (รันใน PowerShell/Command Prompt แบบ
Administrator) — แก้ path ให้ตรงกับที่ clone รีโปไว้จริง:

```powershell
schtasks /Create /TN "XM MT5 Trading Bot" /TR "python C:\path\to\v1\scripts\run_mt5_service.py" /SC MINUTE /MO 30 /RL LIMITED
```

หรือสร้างผ่านหน้าจอ Task Scheduler ก็ได้:

1. เปิด **Task Scheduler** → **Create Task**
2. แท็บ **General**: ตั้งชื่อ เช่น "XM MT5 Trading Bot"
3. แท็บ **Triggers** → **New** → เลือก **Daily**, ติ๊ก **Repeat task every:
   30 minutes**, **for a duration of: Indefinitely**
4. แท็บ **Actions** → **New** → Program/script: path ไปยัง `python.exe`,
   Add arguments: `C:\path\to\v1\scripts\run_mt5_service.py`, Start in:
   `C:\path\to\v1`
5. แท็บ **Conditions**: ไม่ต้องติ๊ก "Start the task only if the computer
   is on AC power" ถ้าใช้โน้ตบุ๊ก (ไม่งั้นจะไม่รันตอนใช้แบตเตอรี่)
6. กด OK

ทุกครั้งที่ task รัน มันจะอ่าน `state/mt5_bot_state.json` และต่อท้าย
`state/mt5_trade_log.jsonl` ไว้เป็นหลักฐาน รันครั้งถัดไปจะอ่านสถานะล่าสุด
ต่อจากที่ครั้งก่อนหยุดไว้ ไม่มีอะไรหายไปแม้คอมจะปิด-เปิดกี่รอบก็ตาม

## 6. ให้ Claude ตรวจสอบ/คุมบอทตอนที่คอมเปิดอยู่

เซสชัน Claude ตัวนี้รันอยู่บนคลาวด์ **เข้าไม่ถึงคอมของคุณได้โดยตรง** —
ถ้าอยากให้ Claude ดู log, เช็คสถานะ, หรือสั่งหยุด/ปรับบอทตัวนี้ตอนที่
คอมเปิดอยู่ ให้เปิด **Claude Code session ใหม่บนคอมเครื่องนั้นเอง** ชี้ไป
ที่โฟลเดอร์ `v1` ที่ clone ไว้ (เซสชันแบบ local ไม่ใช่ cloud) — Claude ที่
รันบนเครื่องนั้นจะอ่าน `state/mt5_bot_state.json` และ
`state/mt5_trade_log.jsonl` ได้ตรง ๆ และสั่งหยุด/แก้ไขอะไรก็ได้ทันที
เหมือนไฟล์ธรรมดาบนเครื่องคุณ
