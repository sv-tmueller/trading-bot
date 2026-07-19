// `supabase functions deploy`'s bundler does not resolve the repo-root deno.json import map, so
// this inline jsr: specifier is load-bearing for deployment.
// deno-lint-ignore no-import-prefix
import { createClient, type SupabaseClient } from "jsr:@supabase/supabase-js@^2.45.0";

// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are auto-injected into Edge Functions.
export function getServiceClient(): SupabaseClient {
  const url = Deno.env.get("SUPABASE_URL");
  const key = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
  if (!url || !key) throw new Error("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set");
  return createClient(url, key, { auth: { persistSession: false } });
}
