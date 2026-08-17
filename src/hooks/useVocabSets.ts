import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import type { VocabSet, VocabWord } from "../lib/types";
import { useAuth } from "../contexts/AuthContext";

const MAX_WORDS_PER_SET = 200;

export function useVocabSets() {
  const { user } = useAuth();
  const [sets, setSets] = useState<VocabSet[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSets = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    const { data, error } = await supabase
      .from("vocab_sets")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: true });
    if (error) setError(error.message);
    else setSets(data as VocabSet[]);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    loadSets();
  }, [loadSets]);

  async function createSet(name: string) {
    if (!user) return null;
    const { data, error } = await supabase
      .from("vocab_sets")
      .insert({ owner_id: user.id, name })
      .select()
      .single();
    if (error) {
      setError(error.message);
      return null;
    }
    setSets((prev) => [...prev, data as VocabSet]);
    return data as VocabSet;
  }

  async function renameSet(id: string, name: string) {
    const { error } = await supabase.from("vocab_sets").update({ name }).eq("id", id);
    if (error) setError(error.message);
    else setSets((prev) => prev.map((s) => (s.id === id ? { ...s, name } : s)));
  }

  async function deleteSet(id: string) {
    // Deleting one's own whole set is an owner action, no moderation needed —
    // moderation only applies to content already shared publicly (see is_public + reports below).
    const { error } = await supabase.from("vocab_sets").delete().eq("id", id);
    if (error) setError(error.message);
    else setSets((prev) => prev.filter((s) => s.id !== id));
  }

  async function togglePublic(id: string, isPublic: boolean) {
    const { error } = await supabase
      .from("vocab_sets")
      .update({ is_public: isPublic })
      .eq("id", id);
    if (error) setError(error.message);
    else setSets((prev) => prev.map((s) => (s.id === id ? { ...s, is_public: isPublic } : s)));
  }

  return { sets, loading, error, createSet, renameSet, deleteSet, togglePublic, reload: loadSets };
}

export function useVocabWords(setId: string | null) {
  const [words, setWords] = useState<VocabWord[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadWords = useCallback(async () => {
    if (!setId) {
      setWords([]);
      return;
    }
    setLoading(true);
    const { data, error } = await supabase
      .from("vocab_words")
      .select("*")
      .eq("set_id", setId)
      .order("created_at", { ascending: true });
    if (error) setError(error.message);
    else setWords(data as VocabWord[]);
    setLoading(false);
  }, [setId]);

  useEffect(() => {
    loadWords();
  }, [loadWords]);

  async function addWord(word: Omit<VocabWord, "id" | "set_id" | "pending_delete" | "created_at">) {
    if (!setId) return;
    if (words.length >= MAX_WORDS_PER_SET) {
      setError(`ชุดนี้เต็มแล้ว (สูงสุด ${MAX_WORDS_PER_SET} คำ)`);
      return;
    }
    const { data, error } = await supabase
      .from("vocab_words")
      .insert({ ...word, set_id: setId })
      .select()
      .single();
    if (error) setError(error.message);
    else setWords((prev) => [...prev, data as VocabWord]);
  }

  async function updateWord(id: string, patch: Partial<VocabWord>) {
    const { error } = await supabase.from("vocab_words").update(patch).eq("id", id);
    if (error) setError(error.message);
    else setWords((prev) => prev.map((w) => (w.id === id ? { ...w, ...patch } : w)));
  }

  // Personal words: instant delete, no admin approval needed.
  // (Old system required admin approval for ALL deletes — that only makes
  // sense for content already shared to the public library.)
  async function deleteWord(id: string) {
    const { error } = await supabase.from("vocab_words").delete().eq("id", id);
    if (error) setError(error.message);
    else setWords((prev) => prev.filter((w) => w.id !== id));
  }

  return { words, loading, error, addWord, updateWord, deleteWord, reload: loadWords };
}
