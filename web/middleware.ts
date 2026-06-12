import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isAuthorized } from "@/lib/auth";

// Optional HTTP Basic auth gate — DEFAULT-OFF (opt-in / default-OFF pattern).
//
// When DASHBOARD_BASIC_AUTH is set (format "user:pass"), every request must
// carry matching Basic credentials or it is rejected with 401. When the env var
// is UNSET (the default), requests pass through unchanged so the current paper-
// soak deployment stays open. Turn this on as the go-live step before pointing
// the dashboard at live/prod keys (URL secrecy is not access control).
//
// The credential comparison is constant-time over SHA-256 digests (finding 12,
// 2026-06-11 review) — see lib/auth.ts.
export async function middleware(req: NextRequest) {
  const expected = process.env.DASHBOARD_BASIC_AUTH;
  if (!expected) return NextResponse.next();

  if (await isAuthorized(req.headers.get("authorization"), expected)) {
    return NextResponse.next();
  }

  return new NextResponse("Authentication required.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="Trading Bot Dashboard"' },
  });
}

// Apply to all routes except Next internals and static assets.
export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
