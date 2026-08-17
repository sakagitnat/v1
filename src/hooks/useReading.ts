import { useCallback, useEffect, useState } from "react";
import { supabase } from "../lib/supabaseClient";
import { useAuth } from "../contexts/AuthContext";

export interface ReadingArticle {
  id: string;
  owner_id: string | null;
  title: string;
  category: "ad" | "review" | "news" | "infographic" | "general";
  body: string;
  time_goal_seconds: number;
  is_public: boolean;
  is_official: boolean;
  created_at: string;
}

export interface ReadingQuestion {
  id: string;
  article_id: string;
  question: string;
  choices: string[];
  correct_index: number;
  question_type: "detail" | "bigpicture";
  explanation: string | null;
}

export function useReadingList() {
  const { user } = useAuth();
  const [articles, setArticles] = useState<ReadingArticle[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!user) return;
    setLoading(true);
    // "รายการของตัวเอง" = owned by user, OR official content already imported.
    // Community import copies rows with owner_id = user.id, so this is simply "mine".
    const { data } = await supabase
      .from("reading_articles")
      .select("*")
      .eq("owner_id", user.id)
      .order("created_at", { ascending: false });
    setArticles((data as ReadingArticle[]) ?? []);
    setLoading(false);
  }, [user]);

  useEffect(() => {
    load();
  }, [load]);

  async function createArticle(input: {
    title: string;
    category: ReadingArticle["category"];
    body: string;
    time_goal_seconds: number;
    questions: Omit<ReadingQuestion, "id" | "article_id">[];
  }) {
    if (!user) return null;
    const { data: article, error } = await supabase
      .from("reading_articles")
      .insert({
        owner_id: user.id,
        title: input.title,
        category: input.category,
        body: input.body,
        time_goal_seconds: input.time_goal_seconds,
      })
      .select()
      .single();
    if (error || !article) return null;

    if (input.questions.length > 0) {
      await supabase.from("reading_questions").insert(
        input.questions.map((q) => ({ ...q, article_id: article.id }))
      );
    }
    await load();
    return article as ReadingArticle;
  }

  async function deleteArticle(id: string) {
    await supabase.from("reading_articles").delete().eq("id", id);
    setArticles((prev) => prev.filter((a) => a.id !== id));
  }

  return { articles, loading, createArticle, deleteArticle, reload: load };
}

export function useReadingDetail(articleId: string | null) {
  const [article, setArticle] = useState<ReadingArticle | null>(null);
  const [questions, setQuestions] = useState<ReadingQuestion[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!articleId) return;
    setLoading(true);
    Promise.all([
      supabase.from("reading_articles").select("*").eq("id", articleId).single(),
      supabase.from("reading_questions").select("*").eq("article_id", articleId),
    ]).then(([a, q]) => {
      setArticle((a.data as ReadingArticle) ?? null);
      setQuestions((q.data as ReadingQuestion[]) ?? []);
      setLoading(false);
    });
  }, [articleId]);

  return { article, questions, loading };
}
