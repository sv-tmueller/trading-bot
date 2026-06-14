// Authorization gate for daily-check and kill-switch Edge Functions (#291).
//
// Supabase deploys these with verify_jwt=ON, so the JWT signature is already
// validated by the platform before our handler runs. This module only inspects
// the (already-trusted) JWT payload to assert the caller holds a service-role
// token — i.e. it came from the pg_cron job, not from an anon-key holder.
//
// requireServiceRole(req): Response | null
//   Returns a 401 Response when the bearer is absent, malformed, or does not
//   carry role "service_role"; returns null when the request is authorized.

const UNAUTHORIZED = () =>
  new Response(JSON.stringify({ error: "unauthorized" }), {
    status: 401,
    headers: { "content-type": "application/json" },
  });

/**
 * Decode a base64url segment (no padding) → UTF-8 string.
 * Standard atob() requires standard base64 (with `+`/`/` and padding); this
 * converts base64url first.
 */
function decodeBase64UrlSegment(segment: string): string {
  // base64url → standard base64: replace `-`→`+`, `_`→`/`, then re-pad.
  const b64 = segment.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  return atob(padded);
}

/**
 * Check the Authorization header of `req` and assert the bearer JWT carries
 * `role: "service_role"`. Returns `null` when authorized, or a `401 Response`
 * for any failure path.
 *
 * Error ordering:
 *   1. No/empty Authorization header → 401
 *   2. Not a "Bearer …" token → 401
 *   3. JWT does not have exactly 3 dot-separated segments → 401
 *   4. Payload segment is not valid base64url JSON → 401
 *   5. Payload is not an object → 401
 *   6. payload.role !== "service_role" → 401
 *   7. null (authorized)
 */
export function requireServiceRole(req: Request): Response | null {
  try {
    const authHeader = req.headers.get("Authorization") ?? "";
    if (!authHeader.startsWith("Bearer ")) {
      return UNAUTHORIZED();
    }

    const token = authHeader.slice("Bearer ".length).trim();
    const parts = token.split(".");
    if (parts.length !== 3) {
      return UNAUTHORIZED();
    }

    let payload: unknown;
    try {
      payload = JSON.parse(decodeBase64UrlSegment(parts[1]));
    } catch {
      return UNAUTHORIZED();
    }

    if (typeof payload !== "object" || payload === null) {
      return UNAUTHORIZED();
    }

    if ((payload as Record<string, unknown>)["role"] !== "service_role") {
      return UNAUTHORIZED();
    }

    return null;
  } catch {
    // Catch-all: any unexpected failure → fail closed.
    return UNAUTHORIZED();
  }
}
