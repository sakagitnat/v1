import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export interface FillBlankItem {
  id: string;
  owner_id: string | null;
  passage: string;
  blanks: { id: string; choices: string[]; correct_index: number }[];
  is_public: boolean;
  is_official: boolean;
  created_at: string;
}

export interface ReorderItem {
  id: string;
  owner_id: string | null;
  sentences: string[]; // correct order
  is_public: boolean;
  is_official: boolean;
  created_at: string;
}

export function useFillBlankList() {
  const { user } = useAuth();
  const [items, setItems] = useState<FillBlankItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    const { data } = await supabase
      .from("writing_fill_blank")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: false });
    setItems((data as FillBlankItem[]) ?? []);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function createItem(passage: string, blanks: FillBlankItem["blanks"]) {
    if (!user) return null;
    const { data, error } = await supabase
      .from("writing_fill_blank")
      .insert({ owner_id: user.id, passage, blanks })
      .select()
      .single();
    if (error) return null;
    await load();
    return data as FillBlankItem;
  }

  async function deleteItem(id: string) {
    await supabase.from("writing_fill_blank").delete().eq("id", id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  return { items, loading, createItem, deleteItem, reload: load };
}

export function useReorderList() {
  const { user } = useAuth();
  const [items, setItems] = useState<ReorderItem[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    const { data } = await supabase
      .from("writing_reorder")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: false });
    setItems((data as ReorderItem[]) ?? []);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function createItem(sentences: string[]) {
    if (!user) return null;
    const { data, error } = await supabase
      .from("writing_reorder")
      .insert({ owner_id: user.id, sentences })
      .select()
      .single();
    if (error) return null;
    await load();
    return data as ReorderItem;
  }

  async function deleteItem(id: string) {
    await supabase.from("writing_reorder").delete().eq("id", id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  return { items, loading, createItem, deleteItem, reload: load };
}
