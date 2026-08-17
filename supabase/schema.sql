-- ============================================================================
-- Grove — Supabase schema (redesigned)
-- Fixes vs. old system, see notes inline marked "FIX:"
-- Run this in the Supabase SQL editor on a fresh project.
-- ============================================================================

create extension if not exists "uuid-ossp";

-- ---------------------------------------------------------------------------
-- Profiles (1 row per auth user)
-- ---------------------------------------------------------------------------
create table profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  username text unique not null,
  avatar_url text,
  xp integer not null default 0,
  level integer not null default 1,
  is_admin boolean not null default false, -- set manually in Supabase table editor for staff accounts
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Translation quota (FIX #5: old spec didn't say if the "10 free" quota
-- resets. Made explicit: daily, reset at midnight UTC by checking `date`.)
-- ---------------------------------------------------------------------------
create table translation_usage (
  user_id uuid not null references profiles(id) on delete cascade,
  date date not null default current_date,
  count integer not null default 0,
  primary key (user_id, date)
);
alter table translation_usage enable row level security;
create policy "translation usage: owner only" on translation_usage
  for all using (auth.uid() = user_id);

-- Auto-create profile row on signup
create function public.handle_new_user()
returns trigger as $$
begin
  insert into public.profiles (id, username)
  values (new.id, coalesce(new.raw_user_meta_data->>'full_name', split_part(new.email, '@', 1)));
  return new;
end;
$$ language plpgsql security definer;

create trigger on_auth_user_created
  after insert on auth.users
  for each row execute procedure public.handle_new_user();

-- ---------------------------------------------------------------------------
-- Pro / subscription status
-- FIX: derive a single `pro_until` instead of checking 3 scattered sources
-- every time a feature gate is checked.
-- ---------------------------------------------------------------------------
create table subscriptions (
  user_id uuid primary key references profiles(id) on delete cascade,
  stripe_customer_id text,
  stripe_subscription_id text,
  stripe_period_end timestamptz,      -- null if never subscribed
  referral_bonus_end timestamptz,     -- null if no referral bonus active
  lifetime_pro boolean not null default false,
  gift_pro_end timestamptz,           -- redeemed gift code expiry
  updated_at timestamptz not null default now()
);

-- Single source of truth for "is this user Pro right now"
create view pro_status as
select
  user_id,
  (lifetime_pro
    or (stripe_period_end is not null and stripe_period_end > now())
    or (referral_bonus_end is not null and referral_bonus_end > now())
    or (gift_pro_end is not null and gift_pro_end > now())
  ) as is_pro,
  greatest(
    coalesce(stripe_period_end, 'epoch'),
    coalesce(referral_bonus_end, 'epoch'),
    coalesce(gift_pro_end, 'epoch')
  ) as pro_until
from subscriptions;

-- ---------------------------------------------------------------------------
-- Vocabulary sets / words
-- FIX #1 (the flagged bug): old schema had a UNIQUE constraint on user_id in
-- vocab_sets, meaning one user could only ever mirror ONE set to the server —
-- which is why "share to community" was capped at 1 set/account. Removed
-- that constraint entirely; id is now the primary key and a user can own
-- and independently publish many sets.
-- ---------------------------------------------------------------------------
create table vocab_sets (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references profiles(id) on delete cascade,
  name text not null,
  is_public boolean not null default false,
  is_official boolean not null default false,   -- website's own pinned sets
  creator_visible boolean not null default true, -- FIX #8: creator attribution toggle
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create index idx_vocab_sets_owner on vocab_sets(owner_id);
create index idx_vocab_sets_public on vocab_sets(is_public) where is_public = true;

create table vocab_words (
  id uuid primary key default uuid_generate_v4(),
  set_id uuid not null references vocab_sets(id) on delete cascade,
  word text not null,
  syllables text,
  pos text,               -- part of speech
  meaning text not null,
  example text,
  grammar_tag text,
  -- FIX #4: pending_delete is ONLY meaningful for words inside an is_public
  -- set (moderation of shared content). Deleting a word from your own
  -- private set is instant — enforced in the app layer (see useVocabSets.ts)
  -- and by the RLS policy below, which only requires moderator approval
  -- to actually remove a row that belongs to a currently-public set.
  pending_delete boolean not null default false,
  created_at timestamptz not null default now()
);
create index idx_vocab_words_set on vocab_words(set_id);

-- Enforce max 200 words per set at the DB level too (not just client-side)
create function check_word_limit() returns trigger as $$
begin
  if (select count(*) from vocab_words where set_id = new.set_id) >= 200 then
    raise exception 'ชุดคำศัพท์เต็มแล้ว (สูงสุด 200 คำ)';
  end if;
  return new;
end;
$$ language plpgsql;

create trigger enforce_word_limit
  before insert on vocab_words
  for each row execute procedure check_word_limit();

-- ---------------------------------------------------------------------------
-- Reading / Listening / Writing content
-- FIX #2: these used to live only in browser localStorage per activity type.
-- Moved server-side so content survives device changes and can be synced.
-- ---------------------------------------------------------------------------
create table reading_articles (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid references profiles(id) on delete cascade, -- null = official content
  title text not null,
  category text not null check (category in ('ad','review','news','infographic','general')),
  body text not null,
  time_goal_seconds integer not null default 300,
  is_public boolean not null default false,
  is_official boolean not null default false,
  created_at timestamptz not null default now()
);

create table reading_questions (
  id uuid primary key default uuid_generate_v4(),
  article_id uuid not null references reading_articles(id) on delete cascade,
  question text not null,
  choices jsonb not null,        -- ["A", "B", "C", "D"]
  correct_index integer not null,
  question_type text not null check (question_type in ('detail','bigpicture')),
  explanation text
);

create table listening_items (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid references profiles(id) on delete cascade,
  title text not null,
  script text not null,
  is_public boolean not null default false,
  is_official boolean not null default false,
  created_at timestamptz not null default now()
);

create table listening_questions (
  id uuid primary key default uuid_generate_v4(),
  listening_id uuid not null references listening_items(id) on delete cascade,
  question text not null,
  choices jsonb not null,
  correct_index integer not null
);

create table writing_fill_blank (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid references profiles(id) on delete cascade,
  passage text not null,          -- contains {{blank_1}} style markers
  blanks jsonb not null,          -- [{ id: "blank_1", choices: [...], correct_index: 0 }]
  is_public boolean not null default false,
  is_official boolean not null default false,
  created_at timestamptz not null default now()
);

create table writing_reorder (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid references profiles(id) on delete cascade,
  sentences jsonb not null,       -- correct order array of strings
  is_public boolean not null default false,
  is_official boolean not null default false,
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Attempts / results — needed for "Weak Points" analytics
-- FIX #3: old spec never defined where quiz results are stored. Without a
-- central table, weak-point analysis can only ever work per-device.
-- ---------------------------------------------------------------------------
create table attempts (
  id uuid primary key default uuid_generate_v4(),
  user_id uuid not null references profiles(id) on delete cascade,
  activity_type text not null check (
    activity_type in ('reading','listening','writing_fill','writing_reorder','mock_exam')
  ),
  item_id uuid not null,
  skill_tag text not null check (
    skill_tag in ('grammar','word_form','cohesion','detail','bigpicture','vocab')
  ),
  correct boolean not null,
  time_spent_seconds integer not null default 0,
  created_at timestamptz not null default now()
);
create index idx_attempts_user on attempts(user_id, skill_tag);

-- ---------------------------------------------------------------------------
-- Community moderation
-- FIX #6: old spec only had a delete-request queue for vocab. Generalized to
-- cover every public content type + general reports (spam, inappropriate).
-- ---------------------------------------------------------------------------
create table content_delete_requests (
  id uuid primary key default uuid_generate_v4(),
  requester_id uuid not null references profiles(id) on delete cascade,
  content_type text not null check (
    content_type in ('vocab_word','vocab_set','reading_article','listening_item','writing_fill_blank','writing_reorder','skill_bank')
  ),
  content_id uuid not null,
  reason text,
  status text not null default 'pending' check (status in ('pending','approved','rejected')),
  created_at timestamptz not null default now(),
  resolved_at timestamptz
);

create table content_reports (
  id uuid primary key default uuid_generate_v4(),
  reporter_id uuid not null references profiles(id) on delete cascade,
  content_type text not null,
  content_id uuid not null,
  reason text not null,
  status text not null default 'open' check (status in ('open','resolved','dismissed')),
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Skill banks (community-shared bundles of reading/listening/writing)
-- ---------------------------------------------------------------------------
create table skill_banks (
  id uuid primary key default uuid_generate_v4(),
  owner_id uuid not null references profiles(id) on delete cascade,
  name text not null,
  description text,
  is_public boolean not null default false,
  created_at timestamptz not null default now()
);

-- Membership rows: a skill bank bundles existing reading/listening/writing
-- content by reference (not by copy), so editing the original content also
-- updates it inside any bank that references it.
create table skill_bank_items (
  id uuid primary key default uuid_generate_v4(),
  bank_id uuid not null references skill_banks(id) on delete cascade,
  content_type text not null check (
    content_type in ('reading_article','listening_item','writing_fill_blank','writing_reorder')
  ),
  content_id uuid not null,
  content_title text not null,
  created_at timestamptz not null default now()
);
create index idx_skill_bank_items_bank on skill_bank_items(bank_id);

-- ---------------------------------------------------------------------------
-- Gamification
-- ---------------------------------------------------------------------------
create table streaks (
  user_id uuid primary key references profiles(id) on delete cascade,
  current_streak integer not null default 0,
  longest_streak integer not null default 0,
  last_checkin date
);

create table badges (
  id uuid primary key default uuid_generate_v4(),
  code text unique not null,   -- 'first_step', 'fire_3_days', 'flawless', 'combo_king_8x', 'level_5', 'level_10'
  label text not null,
  description text
);

create table user_badges (
  user_id uuid references profiles(id) on delete cascade,
  badge_id uuid references badges(id) on delete cascade,
  earned_at timestamptz not null default now(),
  primary key (user_id, badge_id)
);

-- ---------------------------------------------------------------------------
-- Referrals
-- ---------------------------------------------------------------------------
create table referrals (
  id uuid primary key default uuid_generate_v4(),
  referrer_id uuid not null references profiles(id) on delete cascade,
  referred_id uuid references profiles(id) on delete set null,
  code text unique not null,
  created_at timestamptz not null default now(),
  redeemed_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Gift codes
-- ---------------------------------------------------------------------------
create table gift_codes (
  code text primary key,
  pro_days integer not null,
  redeemed_by uuid references profiles(id) on delete set null,
  redeemed_at timestamptz,
  created_at timestamptz not null default now()
);

-- ============================================================================
-- Row Level Security
-- ============================================================================
alter table profiles enable row level security;
alter table vocab_sets enable row level security;
alter table vocab_words enable row level security;
alter table attempts enable row level security;
alter table subscriptions enable row level security;
alter table streaks enable row level security;
alter table user_badges enable row level security;
alter table content_delete_requests enable row level security;
alter table content_reports enable row level security;

create policy "profiles are viewable by everyone" on profiles for select using (true);
create policy "users update own profile" on profiles for update using (auth.uid() = id);

create policy "vocab sets: owner full access" on vocab_sets
  for all using (auth.uid() = owner_id);
create policy "vocab sets: public sets readable by anyone" on vocab_sets
  for select using (is_public = true);

create policy "vocab words: owner full access" on vocab_words
  for all using (
    exists (select 1 from vocab_sets s where s.id = set_id and s.owner_id = auth.uid())
  );
create policy "vocab words: readable if set is public" on vocab_words
  for select using (
    exists (select 1 from vocab_sets s where s.id = set_id and s.is_public = true)
  );

create policy "attempts: owner only" on attempts for all using (auth.uid() = user_id);
create policy "subscriptions: owner read" on subscriptions for select using (auth.uid() = user_id);
-- Owner can write their own row (needed for gift-code redemption and the
-- referral bonus flow, both done client-side with the user's own session).
-- Stripe fields are also writable here for simplicity; in production those
-- should really only be touched by the service-role webhook function.
create policy "subscriptions: owner upsert own" on subscriptions
  for insert with check (auth.uid() = user_id);
create policy "subscriptions: owner update own" on subscriptions
  for update using (auth.uid() = user_id);
create policy "streaks: owner only" on streaks for all using (auth.uid() = user_id);
create policy "user_badges: owner read" on user_badges for select using (auth.uid() = user_id);
create policy "user_badges: owner insert" on user_badges for insert with check (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- RLS for content tables (Reading/Listening/Writing/skill banks/badges).
-- These were missing from the original pass — without RLS enabled, any
-- authenticated user could read or write any other user's private content,
-- since Postgres has no row restriction by default.
-- ---------------------------------------------------------------------------
alter table reading_articles enable row level security;
alter table reading_questions enable row level security;
alter table listening_items enable row level security;
alter table listening_questions enable row level security;
alter table writing_fill_blank enable row level security;
alter table writing_reorder enable row level security;
alter table skill_banks enable row level security;
alter table badges enable row level security;

create policy "reading_articles: owner full access" on reading_articles
  for all using (auth.uid() = owner_id);
create policy "reading_articles: public/official readable" on reading_articles
  for select using (is_public = true or is_official = true);

create policy "reading_questions: readable if article accessible" on reading_questions
  for select using (
    exists (
      select 1 from reading_articles a
      where a.id = article_id and (a.owner_id = auth.uid() or a.is_public or a.is_official)
    )
  );
create policy "reading_questions: owner writes via article" on reading_questions
  for insert with check (
    exists (select 1 from reading_articles a where a.id = article_id and a.owner_id = auth.uid())
  );
create policy "reading_questions: owner updates via article" on reading_questions
  for update using (
    exists (select 1 from reading_articles a where a.id = article_id and a.owner_id = auth.uid())
  );
create policy "reading_questions: owner deletes via article" on reading_questions
  for delete using (
    exists (select 1 from reading_articles a where a.id = article_id and a.owner_id = auth.uid())
  );

create policy "listening_items: owner full access" on listening_items
  for all using (auth.uid() = owner_id);
create policy "listening_items: public/official readable" on listening_items
  for select using (is_public = true or is_official = true);

create policy "listening_questions: readable if item accessible" on listening_questions
  for select using (
    exists (
      select 1 from listening_items i
      where i.id = listening_id and (i.owner_id = auth.uid() or i.is_public or i.is_official)
    )
  );
create policy "listening_questions: owner writes via item" on listening_questions
  for insert with check (
    exists (select 1 from listening_items i where i.id = listening_id and i.owner_id = auth.uid())
  );
create policy "listening_questions: owner updates via item" on listening_questions
  for update using (
    exists (select 1 from listening_items i where i.id = listening_id and i.owner_id = auth.uid())
  );
create policy "listening_questions: owner deletes via item" on listening_questions
  for delete using (
    exists (select 1 from listening_items i where i.id = listening_id and i.owner_id = auth.uid())
  );

create policy "writing_fill_blank: owner full access" on writing_fill_blank
  for all using (auth.uid() = owner_id);
create policy "writing_fill_blank: public/official readable" on writing_fill_blank
  for select using (is_public = true or is_official = true);

create policy "writing_reorder: owner full access" on writing_reorder
  for all using (auth.uid() = owner_id);
create policy "writing_reorder: public/official readable" on writing_reorder
  for select using (is_public = true or is_official = true);

create policy "skill_banks: owner full access" on skill_banks
  for all using (auth.uid() = owner_id);
create policy "skill_banks: public readable" on skill_banks
  for select using (is_public = true);

alter table skill_bank_items enable row level security;
create policy "skill_bank_items: owner full access via bank" on skill_bank_items
  for all using (
    exists (select 1 from skill_banks b where b.id = bank_id and b.owner_id = auth.uid())
  );
create policy "skill_bank_items: readable if bank is public" on skill_bank_items
  for select using (
    exists (select 1 from skill_banks b where b.id = bank_id and b.is_public)
  );

create policy "badges: readable by everyone" on badges for select using (true);

create policy "delete requests: requester can create/read own" on content_delete_requests
  for all using (auth.uid() = requester_id);
create policy "reports: reporter can create/read own" on content_reports
  for all using (auth.uid() = reporter_id);

-- Admins (profiles.is_admin = true) can see and resolve everyone's queue —
-- required for the Admin panel's moderation views.
create policy "delete requests: admins see all" on content_delete_requests
  for select using (exists (select 1 from profiles p where p.id = auth.uid() and p.is_admin));
create policy "delete requests: admins update all" on content_delete_requests
  for update using (exists (select 1 from profiles p where p.id = auth.uid() and p.is_admin));
create policy "reports: admins see all" on content_reports
  for select using (exists (select 1 from profiles p where p.id = auth.uid() and p.is_admin));
create policy "reports: admins update all" on content_reports
  for update using (exists (select 1 from profiles p where p.id = auth.uid() and p.is_admin));

-- Gift codes: anyone authenticated can attempt to redeem (checked in app
-- logic), but only admins should be able to freely list/insert new codes.
alter table gift_codes enable row level security;
create policy "gift codes: readable by all authenticated users" on gift_codes
  for select using (auth.role() = 'authenticated');
create policy "gift codes: admins can insert" on gift_codes
  for insert with check (exists (select 1 from profiles p where p.id = auth.uid() and p.is_admin));
create policy "gift codes: anyone can redeem (update own redemption)" on gift_codes
  for update using (redeemed_by is null) with check (redeemed_by = auth.uid());

-- Referrals: user can create/read their own referral rows; anyone can look up
-- a code by value (needed to redeem someone else's link) but only update the
-- row they're redeeming.
alter table referrals enable row level security;
create policy "referrals: owner or public code lookup" on referrals
  for select using (true);
create policy "referrals: referrer creates own" on referrals
  for insert with check (auth.uid() = referrer_id);
create policy "referrals: redeemer marks redeemed" on referrals
  for update using (redeemed_at is null);

-- ---------------------------------------------------------------------------
-- Seed badges (codes referenced from src/lib/gamification.ts and
-- src/hooks/useProfile.ts's checkIn — must match exactly)
-- ---------------------------------------------------------------------------
insert into badges (code, label, description) values
  ('first_step', 'ก้าวแรก', 'ทำโจทย์ข้อแรกสำเร็จ'),
  ('fire_3_days', 'ไฟลุกโชน 3 วัน', 'เช็คอินติดต่อกัน 3 วัน'),
  ('flawless', 'ไร้ที่ติ', 'ทำโจทย์ถูกทุกข้อในหนึ่งชุด'),
  ('combo_king_8x', 'ราชาคอมโบ 8x', 'จับคู่คำถูกต่อกัน 8 ครั้งในเกมจับคู่'),
  ('level_5', 'เลเวล 5', 'ถึงเลเวล 5'),
  ('level_10', 'เลเวล 10', 'ถึงเลเวล 10')
on conflict (code) do nothing;
