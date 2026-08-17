import { createClient } from "@supabase/supabase-js";

// These come from Cloudflare Pages build-time env vars (see README.md).
// VITE_ prefix is required for Vite to expose them to client code.
const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string;

if (!supabaseUrl || !supabaseAnonKey) {
  // eslint-disable-next-line no-console
  console.error(
    "Missing VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. Set them in .env.local (dev) or Cloudflare Pages env vars (prod)."
  );
}

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
