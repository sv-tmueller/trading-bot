import { NextRequest, NextResponse } from "next/server";

// Optional HTTP Basic auth gate — DEFAULT-OFF (opt-in / default-OFF pattern).
//
// When DASHBOARD_BASIC_AUTH is set (format "user:pass"), every request must
// carry matching Basic credentials or it is rejected with 401. When the env var
// is UNSET (the default), requests pass through unchanged so the current paper-
// soak deployment stays open. Turn this on as the go-live step before pointing
// the dashboard at live/prod keys (URL secrecy is not access control).
export function middleware(req: NextRequest) {
  const expected = process.env.DASHBOARD_BASIC_AUTH;
  if (!expected) return NextResponse.next();

  const header = req.headers.get("authorization");
  if (header?.startsWith("Basic ")) {
    const decoded = atob(header.slice("Basic ".length));
    if (decoded === expected) return NextResponse.next();
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
