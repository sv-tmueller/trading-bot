import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";
import { isAuthorized } from "@/lib/auth";

// HTTP Basic Auth for the whole dashboard (2026-06-11 code review, finding 12).
// The page renders live account equity, positions, trades, and kill-switch
// state, so it must never be served unauthenticated. Credentials come from the
// server-side env vars DASHBOARD_USER / DASHBOARD_PASSWORD (never NEXT_PUBLIC_).
//
// Fails closed: if DASHBOARD_PASSWORD is unset, every request gets a 503
// instead of data. Wrong/missing credentials get a 401 with a Basic challenge.

export async function middleware(req: NextRequest) {
  const user = process.env.DASHBOARD_USER;
  const password = process.env.DASHBOARD_PASSWORD;

  if (!password) {
    return new NextResponse("dashboard auth not configured", { status: 503 });
  }

  if (await isAuthorized(req.headers.get("authorization"), user ?? "", password)) {
    return NextResponse.next();
  }

  return new NextResponse("Unauthorized", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="trading-bot"' },
  });
}

export const config = {
  // Everything except Next.js static assets and the favicon.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
