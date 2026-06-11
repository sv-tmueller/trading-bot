// Credential check for the dashboard's HTTP Basic Auth middleware. Pure helper
// (no Next.js imports) so it can be unit-tested in isolation; runs on the edge
// runtime, so it uses only Web APIs (atob, crypto.subtle).

// Constant-time string comparison: hash both sides with SHA-256 and compare the
// fixed-length digests byte-wise, accumulating the difference instead of
// returning early. The hashing also masks length differences between the
// supplied and expected values.
async function digestsEqual(a: string, b: string): Promise<boolean> {
  const enc = new TextEncoder();
  const [da, db] = await Promise.all([
    crypto.subtle.digest("SHA-256", enc.encode(a)),
    crypto.subtle.digest("SHA-256", enc.encode(b)),
  ]);
  const ba = new Uint8Array(da);
  const bb = new Uint8Array(db);
  let diff = 0;
  for (let i = 0; i < ba.length; i++) diff |= ba[i] ^ bb[i];
  return diff === 0;
}

// Parses an `Authorization: Basic <base64(user:password)>` header. Returns null
// on a missing/malformed header.
export function parseBasicAuth(header: string | null): { user: string; password: string } | null {
  if (!header) return null;
  const m = header.match(/^Basic\s+(.+)$/i);
  if (!m) return null;
  let decoded: string;
  try {
    decoded = atob(m[1]);
  } catch {
    return null;
  }
  const sep = decoded.indexOf(":");
  if (sep === -1) return null;
  return { user: decoded.slice(0, sep), password: decoded.slice(sep + 1) };
}

// True iff the Authorization header carries the expected Basic credentials.
// Both comparisons always run (no short-circuit on a wrong username) and each
// is constant-time over the SHA-256 digests.
export async function isAuthorized(
  header: string | null,
  expectedUser: string,
  expectedPassword: string,
): Promise<boolean> {
  const creds = parseBasicAuth(header);
  if (!creds) return false;
  const [userOk, passwordOk] = await Promise.all([
    digestsEqual(creds.user, expectedUser),
    digestsEqual(creds.password, expectedPassword),
  ]);
  return userOk && passwordOk;
}
