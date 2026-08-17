export interface Profile {
  id: string;
  username: string;
  avatar_url: string | null;
  xp: number;
  level: number;
  created_at: string;
}

export interface VocabSet {
  id: string;
  owner_id: string;
  name: string;
  is_public: boolean;
  is_official: boolean;
  creator_visible: boolean;
  word_count: number;
  created_at: string;
  updated_at: string;
}

export interface VocabWord {
  id: string;
  set_id: string;
  word: string;
  syllables: string | null;
  pos: string | null; // part of speech
  meaning: string;
  example: string | null;
  grammar_tag: string | null;
  pending_delete: boolean;
  created_at: string;
}

export type SkillTag =
  | "grammar"
  | "word_form"
  | "cohesion"
  | "detail"
  | "bigpicture"
  | "vocab";

export interface Attempt {
  id: string;
  user_id: string;
  activity_type: "reading" | "listening" | "writing_fill" | "writing_reorder" | "mock_exam";
  item_id: string;
  skill_tag: SkillTag;
  correct: boolean;
  time_spent_seconds: number;
  created_at: string;
}
