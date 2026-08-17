import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export interface ListeningItem {
  id: string;
  owner_id: string | null;
  title: string;
  script: string;
  is_public: boolean;
  is_official: boolean;
  created_at: string;
}

export interface ListeningQuestion {
  id: string;
  listening_id: string;
  question: string;
  choices: string[];
  correct_index: number;
}

export function useListeningList() {
  const { user } = useAuth();
  const [items, setItems] = useState<ListeningItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    const { data } = await supabase
      .from("listening_items")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: false });
    setItems((data as ListeningItem[]) ?? []);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function createItem(input: {
    title: string;
    script: string;
    questions: Omit<ListeningQuestion, "id" | "listening_id">[];
  }) {
    if (!user) return null;
    const { data: item, error } = await supabase
      .from("listening_items")
      .insert({ owner_id: user.id, title: input.title, script: input.script })
      .select()
      .single();
    if (error || !item) return null;
    if (input.questions.length > 0) {
      await supabase
        .from("listening_questions")
        .insert(input.questions.map((q) => ({ ...q, listening_id: item.id })));
    }
    await load();
    return item as ListeningItem;
  }

  async function deleteItem(id: string) {
    await supabase.from("listening_items").delete().eq("id", id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  return { items, loading, createItem, deleteItem, reload: load };
}

export function useListeningDetail(itemId: string | null) {
  const [item, setItem] = useState<ListeningItem | null>(null);
  const [questions, setQuestions] = useState<ListeningQuestion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!itemId) return;
    setLoading(true);
    Promise.all([
      supabase.from("listening_items").select("*").eq("id", itemId).single(),
      supabase.from("listening_questions").select("*").eq("listening_id", itemId),
    ]).then(([i, q]) => {
      setItem((i.data as ListeningItem) ?? null);
      setQuestions((q.data as ListeningQuestion[]) ?? []);
      setLoading(false);
    });
  }, [itemId]);

  return { item, questions, loading };
}
