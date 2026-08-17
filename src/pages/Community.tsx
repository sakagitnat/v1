import { useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

type Tab = "vocab" | "reading" | "listening" | "writing" | "skillbank";

export default function Community() {
  const [tab, setTab] = useState<Tab>("vocab");
  return (
    <div className="p-10 max-w-3xl">
      <h1 className="text-2xl font-bold text-grove-800 mb-1">คลังสาธารณะ</h1>
      <p className="text-gray-500 mb-6">
        นำเข้าเนื้อหาจากเว็บไซต์หรือสมาชิกคนอื่น — นำเข้าแล้วจะเป็นสำเนาใหม่ ไม่แทนที่ของเดิม
      </p>
      <div className="flex gap-2 mb-6">
        {(
          [
            ["vocab", "ชุดคำศัพท์"],
            ["reading", "Reading"],
            ["listening", "Listening"],
            ["writing", "Writing"],
            ["skillbank", "Skill Bank"],
          ] as [Tab, string][]
        ).map(([key, label]) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={`px-4 py-1.5 rounded-full text-sm border ${
              tab === key ? "bg-grove-600 text-white border-grove-600" : "bg-white border-grove-200"
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "vocab" && <VocabCommunity />}
      {tab === "reading" && <ReadingCommunity />}
      {tab === "listening" && <ListeningCommunity />}
      {tab === "writing" && <WritingCommunity />}
      {tab === "skillbank" && <SkillBankCommunity />}
    </div>
  );
}

function Badge({ official }: { official: boolean }) {
  return (
    <span
      className={`text-xs px-2 py-0.5 rounded-full ${
        official ? "bg-grove-100 text-grove-700" : "bg-yellow-50 text-yellow-700"
      }`}
    >
      {official ? "เนื้อหาทางการจากเว็บไซต์" : "สร้างโดยสมาชิกในชุมชน"}
    </span>
  );
}

function VocabCommunity() {
  const { user } = useAuth();
  const [sets, setSets] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase
      .from("vocab_sets")
      .select("*")
      .eq("is_public", true)
      .order("is_official", { ascending: false })
      .then(({ data }) => {
        setSets(data ?? []);
        setLoading(false);
      });
  }, []);

  async function importSet(set: any) {
    if (!user) return;
    const { data: newSet } = await supabase
      .from("vocab_sets")
      .insert({ owner_id: user.id, name: `${set.name} (นำเข้า)` })
      .select()
      .single();
    if (!newSet) return;
    const { data: words } = await supabase.from("vocab_words").select("*").eq("set_id", set.id);
    if (words && words.length > 0) {
      await supabase.from("vocab_words").insert(
        words.map((w) => ({
          set_id: newSet.id,
          word: w.word,
          syllables: w.syllables,
          pos: w.pos,
          meaning: w.meaning,
          example: w.example,
          grammar_tag: w.grammar_tag,
        }))
      );
    }
    alert(`นำเข้า "${set.name}" เป็นชุดใหม่แล้ว`);
  }

  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;
  if (sets.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีชุดสาธารณะ</div>;

  return (
    <div className="space-y-2">
      {sets.map((s) => (
        <div key={s.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
          <div>
            <div className="font-medium text-grove-800">{s.name}</div>
            <div className="mt-1"><Badge official={s.is_official} /></div>
          </div>
          <button
            onClick={() => importSet(s)}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-3 py-1.5 text-sm"
          >
            นำเข้า
          </button>
        </div>
      ))}
    </div>
  );
}

function ReadingCommunity() {
  const { user } = useAuth();
  const [articles, setArticles] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase
      .from("reading_articles")
      .select("*")
      .eq("is_public", true)
      .order("is_official", { ascending: false })
      .then(({ data }) => {
        setArticles(data ?? []);
        setLoading(false);
      });
  }, []);

  async function importArticle(a: any) {
    if (!user) return;
    const { data: newArticle } = await supabase
      .from("reading_articles")
      .insert({
        owner_id: user.id,
        title: a.title,
        category: a.category,
        body: a.body,
        time_goal_seconds: a.time_goal_seconds,
      })
      .select()
      .single();
    if (!newArticle) return;
    const { data: qs } = await supabase.from("reading_questions").select("*").eq("article_id", a.id);
    if (qs && qs.length > 0) {
      await supabase.from("reading_questions").insert(
        qs.map((q) => ({
          article_id: newArticle.id,
          question: q.question,
          choices: q.choices,
          correct_index: q.correct_index,
          question_type: q.question_type,
          explanation: q.explanation,
        }))
      );
    }
    alert(`นำเข้า "${a.title}" แล้ว`);
  }

  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;
  if (articles.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีบทความสาธารณะ</div>;

  return (
    <div className="space-y-2">
      {articles.map((a) => (
        <div key={a.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
          <div>
            <div className="font-medium text-grove-800">{a.title}</div>
            <div className="mt-1"><Badge official={a.is_official} /></div>
          </div>
          <button
            onClick={() => importArticle(a)}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-3 py-1.5 text-sm"
          >
            นำเข้า
          </button>
        </div>
      ))}
    </div>
  );
}

function ListeningCommunity() {
  const { user } = useAuth();
  const [items, setItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    supabase
      .from("listening_items")
      .select("*")
      .eq("is_public", true)
      .then(({ data }) => {
        setItems(data ?? []);
        setLoading(false);
      });
  }, []);

  async function importItem(it: any) {
    if (!user) return;
    const { data: newItem } = await supabase
      .from("listening_items")
      .insert({ owner_id: user.id, title: it.title, script: it.script })
      .select()
      .single();
    if (!newItem) return;
    const { data: qs } = await supabase.from("listening_questions").select("*").eq("listening_id", it.id);
    if (qs && qs.length > 0) {
      await supabase.from("listening_questions").insert(
        qs.map((q) => ({
          listening_id: newItem.id,
          question: q.question,
          choices: q.choices,
          correct_index: q.correct_index,
        }))
      );
    }
    alert(`นำเข้า "${it.title}" แล้ว`);
  }

  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;
  if (items.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มีบทสนทนาสาธารณะ</div>;

  return (
    <div className="space-y-2">
      {items.map((it) => (
        <div key={it.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
          <div>
            <div className="font-medium text-grove-800">{it.title}</div>
            <div className="mt-1"><Badge official={it.is_official} /></div>
          </div>
          <button
            onClick={() => importItem(it)}
            className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-3 py-1.5 text-sm"
          >
            นำเข้า
          </button>
        </div>
      ))}
    </div>
  );
}

function SkillBankCommunity() {
  const { user } = useAuth();
  const [banks, setBanks] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [importingId, setImportingId] = useState<string | null>(null);

  useEffect(() => {
    supabase
      .from("skill_banks")
      .select("*")
      .eq("is_public", true)
      .then(({ data }) => {
        setBanks(data ?? []);
        setLoading(false);
      });
  }, []);

  async function importBank(bank: any) {
    if (!user) return;
    setImportingId(bank.id);
    const { data: items } = await supabase.from("skill_bank_items").select("*").eq("bank_id", bank.id);
    const { data: newBank } = await supabase
      .from("skill_banks")
      .insert({ owner_id: user.id, name: `${bank.name} (นำเข้า)`, description: bank.description })
      .select()
      .single();

    if (newBank && items) {
      for (const item of items) {
        // Copy the underlying content (same pattern as the single-item importers
        // above) so the user owns an independent copy, then reference that
        // copy from their new bank.
        let newContentId: string | null = null;

        if (item.content_type === "reading_article") {
          const { data: orig } = await supabase.from("reading_articles").select("*").eq("id", item.content_id).single();
          if (orig) {
            const { data: copy } = await supabase
              .from("reading_articles")
              .insert({ owner_id: user.id, title: orig.title, category: orig.category, body: orig.body, time_goal_seconds: orig.time_goal_seconds })
              .select()
              .single();
            newContentId = copy?.id ?? null;
            if (copy) {
              const { data: qs } = await supabase.from("reading_questions").select("*").eq("article_id", orig.id);
              if (qs?.length) {
                await supabase.from("reading_questions").insert(
                  qs.map((q) => ({ article_id: copy.id, question: q.question, choices: q.choices, correct_index: q.correct_index, question_type: q.question_type, explanation: q.explanation }))
                );
              }
            }
          }
        } else if (item.content_type === "listening_item") {
          const { data: orig } = await supabase.from("listening_items").select("*").eq("id", item.content_id).single();
          if (orig) {
            const { data: copy } = await supabase
              .from("listening_items")
              .insert({ owner_id: user.id, title: orig.title, script: orig.script })
              .select()
              .single();
            newContentId = copy?.id ?? null;
            if (copy) {
              const { data: qs } = await supabase.from("listening_questions").select("*").eq("listening_id", orig.id);
              if (qs?.length) {
                await supabase.from("listening_questions").insert(
                  qs.map((q) => ({ listening_id: copy.id, question: q.question, choices: q.choices, correct_index: q.correct_index }))
                );
              }
            }
          }
        } else if (item.content_type === "writing_fill_blank") {
          const { data: orig } = await supabase.from("writing_fill_blank").select("*").eq("id", item.content_id).single();
          if (orig) {
            const { data: copy } = await supabase
              .from("writing_fill_blank")
              .insert({ owner_id: user.id, passage: orig.passage, blanks: orig.blanks })
              .select()
              .single();
            newContentId = copy?.id ?? null;
          }
        } else if (item.content_type === "writing_reorder") {
          const { data: orig } = await supabase.from("writing_reorder").select("*").eq("id", item.content_id).single();
          if (orig) {
            const { data: copy } = await supabase
              .from("writing_reorder")
              .insert({ owner_id: user.id, sentences: orig.sentences })
              .select()
              .single();
            newContentId = copy?.id ?? null;
          }
        }

        if (newContentId) {
          await supabase.from("skill_bank_items").insert({
            bank_id: newBank.id,
            content_type: item.content_type,
            content_id: newContentId,
            content_title: item.content_title,
          });
        }
      }
    }
    setImportingId(null);
    alert(`นำเข้า "${bank.name}" พร้อมเนื้อหาทั้งหมดแล้ว`);
  }

  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;
  if (banks.length === 0) return <div className="text-gray-400 text-sm py-8 text-center">ยังไม่มี Skill Bank สาธารณะ</div>;

  return (
    <div className="space-y-2">
      {banks.map((b) => (
        <div key={b.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
          <div>
            <div className="font-medium text-grove-800">{b.name}</div>
            {b.description && <div className="text-xs text-gray-400">{b.description}</div>}
          </div>
          <button
            onClick={() => importBank(b)}
            disabled={importingId === b.id}
            className="bg-grove-600 hover:bg-grove-700 disabled:opacity-50 text-white rounded-lg px-3 py-1.5 text-sm"
          >
            {importingId === b.id ? "กำลังนำเข้า..." : "นำเข้าทั้งชุด"}
          </button>
        </div>
      ))}
    </div>
  );
}

function WritingCommunity() {
  const { user } = useAuth();
  const [fillItems, setFillItems] = useState<any[]>([]);
  const [reorderItems, setReorderItems] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      supabase.from("writing_fill_blank").select("*").eq("is_public", true),
      supabase.from("writing_reorder").select("*").eq("is_public", true),
    ]).then(([f, r]) => {
      setFillItems(f.data ?? []);
      setReorderItems(r.data ?? []);
      setLoading(false);
    });
  }, []);

  async function importFill(it: any) {
    if (!user) return;
    await supabase
      .from("writing_fill_blank")
      .insert({ owner_id: user.id, passage: it.passage, blanks: it.blanks });
    alert("นำเข้าโจทย์เติมคำแล้ว");
  }
  async function importReorder(it: any) {
    if (!user) return;
    await supabase.from("writing_reorder").insert({ owner_id: user.id, sentences: it.sentences });
    alert("นำเข้าโจทย์เรียงประโยคแล้ว");
  }

  if (loading) return <div className="text-gray-400 text-sm">กำลังโหลด...</div>;

  return (
    <div className="space-y-4">
      <div>
        <div className="text-sm font-medium text-grove-700 mb-2">โจทย์เติมคำ</div>
        {fillItems.length === 0 && <div className="text-gray-400 text-sm">ยังไม่มี</div>}
        <div className="space-y-2">
          {fillItems.map((it) => (
            <div key={it.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
              <div className="text-sm truncate flex-1">{it.passage.slice(0, 60)}...</div>
              <button
                onClick={() => importFill(it)}
                className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-3 py-1.5 text-sm ml-3"
              >
                นำเข้า
              </button>
            </div>
          ))}
        </div>
      </div>
      <div>
        <div className="text-sm font-medium text-grove-700 mb-2">โจทย์เรียงประโยค</div>
        {reorderItems.length === 0 && <div className="text-gray-400 text-sm">ยังไม่มี</div>}
        <div className="space-y-2">
          {reorderItems.map((it) => (
            <div key={it.id} className="bg-white rounded-xl border border-grove-100 p-4 flex items-center justify-between">
              <div className="text-sm">{it.sentences.length} ประโยค</div>
              <button
                onClick={() => importReorder(it)}
                className="bg-grove-600 hover:bg-grove-700 text-white rounded-lg px-3 py-1.5 text-sm"
              >
                นำเข้า
              </button>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
