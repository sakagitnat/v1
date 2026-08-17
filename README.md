# Grove

แอปฝึกภาษาอังกฤษครบวงจร — Flashcard, Reading, Listening, Writing, Mock Exam, Community, Skill Bank, Pro/Stripe, Admin
Frontend: React + TypeScript + Vite + Tailwind, deploy บน Cloudflare Pages
Backend: Supabase (Auth + Postgres) + Cloudflare Pages Functions (Stripe)

## สถานะ: ครบทุกฟีเจอร์ในสเปกเดิมแล้ว

- ✅ Login ด้วย Google
- ✅ Flashcard: หลายชุด, ท่องคำ (batch unlock), เกมจับคู่ (ชีวิต/คอมโบ+แบดจ์), **Crossword** (auto-generate จากคำในชุด), เรียง a-z, แชร์สาธารณะ (Pro)
- ✅ Reading: รายการของตัวเอง, แตะคำแปล→เพิ่มคำศัพท์ (โควตา 10/วันสำหรับ non-Pro), quiz จับเวลา, เพิ่มเอง
- ✅ Listening: TTS (เลือกเสียง/ความเร็ว), quiz, เพิ่มเอง
- ✅ Writing: เติมคำ, เรียงประโยค, ระบุชนิดคำ
- ✅ สอบจำลอง, จุดอ่อน (วิเคราะห์จากตาราง attempts จริง)
- ✅ คลังสาธารณะ: คำศัพท์/Reading/Listening/Writing/**Skill Bank** — import เป็นสำเนาใหม่เสมอ
- ✅ **Skill Bank**: รวมเนื้อหาที่มีอยู่แล้วเป็นชุด แชร์/นำเข้าทั้งชุดได้ (Pro)
- ✅ จัดการเนื้อหาของฉัน, เพิ่มเนื้อหา (hub)
- ✅ **นำเข้าจาก PDF**: ใช้ pdf.js ดึงข้อความจริง + heuristic จับคู่ "คำ-ความหมาย" อัตโนมัติ พร้อมพรีวิวให้ตรวจก่อนบันทึก (นำเข้าเป็นชุดคำศัพท์ หรือบทความ Reading)
- ✅ นำเข้าจาก JSON
- ✅ โปรไฟล์: เลเวล/XP, streak, แบดจ์, leaderboard
- ✅ Pro: Stripe Checkout + Billing Portal ผ่าน Cloudflare Pages Functions, **webhook verify signature จริง** (HMAC-SHA256 ตามสเปก Stripe, ใช้ Web Crypto API)
- ✅ ชวนเพื่อน + แลกโค้ดของขวัญ
- ✅ แอดมิน: คิวลบ/รายงาน, ออกโค้ดของขวัญ
- ✅ ตั้งค่า: ธีม/เสียง/ภาษา

### ข้อจำกัดที่ควรรู้ก่อนใช้งานจริง (ไม่ใช่บั๊ก แต่เป็นสิ่งที่ควร harden เพิ่มก่อนขึ้น production)
- PDF import เป็น heuristic (จับรูปแบบ "word - meaning" ฯลฯ) — ไม่ใช่ NLP เต็มรูปแบบ ต้องตรวจก่อนบันทึกเสมอ (มี preview ให้แล้ว)
- Crossword generator เป็นแบบ greedy ไม่ใช่ solver เต็มรูปแบบ — คำที่ไม่มีตัวอักษรร่วมกับคำอื่นจะถูกข้าม (แจ้งในหน้าเกม)
- Stripe subscription upsert ยังไม่มี idempotency key กันเหตุการณ์ซ้ำจาก Stripe retry — เพิ่มได้โดยเก็บ `event.id` ที่เคยประมวลผลแล้ว
- ทดสอบ (unit/e2e tests) ยังไม่มี — โค้ดทั้งหมดยังไม่ได้รันจริงเพราะ sandbox นี้ไม่มี network ให้ `npm install`

## Setup

### 1. Supabase
1. สร้างโปรเจกต์ที่ [supabase.com](https://supabase.com)
2. SQL Editor → รันไฟล์ `supabase/schema.sql` ทั้งไฟล์ (มี RLS + seed แบดจ์มาให้)
3. Authentication → Providers → เปิด Google OAuth
4. Authentication → URL Configuration → เพิ่ม URL จริง + `http://localhost:5173`
5. Project Settings → API → คัดลอก `Project URL`, `anon public key`, และ `service_role` key (ใช้เฉพาะฝั่ง Cloudflare Function เท่านั้น)
6. Table Editor → `profiles` → set `is_admin = true` ให้บัญชีตัวเอง

### 2. รันในเครื่อง
```bash
npm install
cp .env.example .env.local   # ใส่ VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY
npm run dev
```

### 3. Deploy Cloudflare Pages
1. Push ขึ้น GitHub → Cloudflare Dashboard → Workers & Pages → Create → Pages → Connect to Git
2. Build command `npm run build`, output `dist`
3. Environment variables:
   - `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`
   - Stripe (ถ้าจะเปิดใช้): `STRIPE_SECRET_KEY`, `STRIPE_PRICE_MONTHLY`, `STRIPE_PRICE_YEARLY`,
     `STRIPE_WEBHOOK_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `PUBLIC_SITE_URL`
4. Stripe Dashboard → Webhooks → เพิ่ม endpoint `https://your-site.pages.dev/api/stripe-webhook`
   → เลือก events: `checkout.session.completed`, `customer.subscription.updated`, `customer.subscription.deleted`
5. กลับไปเพิ่ม URL จริงใน Supabase Auth → URL Configuration

## โครงสร้างโปรเจกต์
```
src/
  lib/            supabase client, types, gamification, attempt logging, POS drill data, PDF import
  contexts/       AuthContext
  hooks/          หนึ่ง hook ต่อหนึ่งโดเมนข้อมูล
  components/     Layout, QuizRunner, FlashcardGames, Crossword, ReferralProcessor
  pages/          หนึ่งไฟล์ต่อหนึ่งเมนู
functions/
  _stripeVerify.ts        Stripe webhook signature verification (Web Crypto)
  api/                     Cloudflare Pages Functions (checkout / webhook / billing portal)
supabase/
  schema.sql      DB schema + RLS ครบทุกตาราง + seed badges
```

## หมายเหตุเรื่องชื่อแอป
ใช้ "Grove" ในโค้ด — เปลี่ยนได้โดยค้นหาคำว่า "Grove" ใน `index.html` และ `Layout.tsx`
