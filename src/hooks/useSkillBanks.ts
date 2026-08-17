import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export interface SkillBank {
  id: string;
  owner_id: string;
  name: string;
  description: string | null;
  is_public: boolean;
  created_at: string;
}

export interface SkillBankItem {
  id: string;
  bank_id: string;
  content_type: "reading_article" | "listening_item" | "writing_fill_blank" | "writing_reorder";
  content_id: string;
  content_title: string;
}

export function useSkillBanks() {
  const { user } = useAuth();
  const [banks, setBanks] = useState<SkillBank[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    const { data } = await supabase
      .from("skill_banks")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: false });
    setBanks((data as SkillBank[]) ?? []);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function createBank(name: string, description: string) {
    if (!user) return null;
    const { data, error } = await supabase
      .from("skill_banks")
      .insert({ owner_id: user.id, name, description: description || null })
      .select()
      .single();
    if (error) return null;
    await load();
    return data as SkillBank;
  }

  async function togglePublic(id: string, isPublic: boolean) {
    await supabase.from("skill_banks").update({ is_public: isPublic }).eq("id", id);
    setBanks((prev) => prev.map((b) => (b.id === id ? { ...b, is_public: isPublic } : b)));
  }

  async function deleteBank(id: string) {
    await supabase.from("skill_banks").delete().eq("id", id);
    setBanks((prev) => prev.filter((b) => b.id !== id));
  }

  return { banks, loading, createBank, togglePublic, deleteBank, reload: load };
}

export function useSkillBankItems(bankId: string | null) {
  const [items, setItems] = useState<SkillBankItem[]>([]);
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    if (!bankId) {
      setItems([]);
      return;
    }
    setLoading(true);
    const { data } = await supabase.from("skill_bank_items").select("*").eq("bank_id", bankId);
    setItems((data as SkillBankItem[]) ?? []);
    setLoading(false);
  }, [bankId]);

  useEffect(() => {
    load();
  }, [load]);

  async function addItem(contentType: SkillBankItem["content_type"], contentId: string, title: string) {
    if (!bankId) return;
    await supabase
      .from("skill_bank_items")
      .insert({ bank_id: bankId, content_type: contentType, content_id: contentId, content_title: title });
    await load();
  }

  async function removeItem(id: string) {
    await supabase.from("skill_bank_items").delete().eq("id", id);
    setItems((prev) => prev.filter((i) => i.id !== id));
  }

  return { items, loading, addItem, removeItem, reload: load };
}
