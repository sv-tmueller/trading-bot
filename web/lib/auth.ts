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

// Decodes an `Authorization: Basic <base64(user:password)>` header to the raw
// "user:password" string. Returns null on a missing/malformed header.
export function decodeBasicAuth(header: string | null): string | null {
  if (!header) return null;
  const m = header.match(/^Basic\s+(.+)$/i);
  if (!m) return null;
  try {
    return atob(m[1]);
  } catch {
    return null;
  }
}

// True iff the Authorization header carries Basic credentials matching the
// expected "user:pass" string (DASHBOARD_BASIC_AUTH). The comparison is
// constant-time over the SHA-256 digests (finding 12, 2026-06-11 review).
export async function isAuthorized(header: string | null, expected: string): Promise<boolean> {
  const decoded = decodeBasicAuth(header);
  if (decoded === null) return false;
  return await digestsEqual(decoded, expected);
}
