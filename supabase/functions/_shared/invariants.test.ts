/**
 * Invariant enforcement: "No LLM in the trading path"
 *
 * Scans every non-test .ts file under supabase/functions/ and fails if any
 * forbidden model-SDK import specifier appears. Enforces CLAUDE.md Architectural
 * invariant #1. See docs/superpowers/specs/2026-06-14-invariant-enforcement-in-template-model-design.md
 */
import { assertEquals, assertNotEquals } from "@std/assert";

// ---------------------------------------------------------------------------
// Forbidden import specifiers (case-insensitive, matched on extracted specifier
// — NOT on raw source text, so comments cannot trigger false positives).
// ---------------------------------------------------------------------------
const FORBIDDEN = [
  "anthropic",
  "@anthropic-ai",
  "openai",
  "cohere",
  "mistral",
  "mistralai",
  "generativeai",
  "@google/genai",
  "langchain",
];

/**
 * Extract module specifiers from an import / export / require expression and
 * test each against the forbidden set. Returns the matched forbidden term,
 * or null if the source is clean.
 *
 * Matches:
 *   import … from "X"      (named / default / namespace import)
 *   export … from "X"      (re-export)
 *   import "X"              (side-effect import)
 *   import("X")             (dynamic import)
 *   require("X")            (CommonJS)
 * Single and double quoted.  Does NOT match specifiers inside // or block comments.
 */
export function findForbiddenImport(source: string): string | null {
  // Remove line comments first to avoid matching "anthropic" inside a //-comment.
  // Block comments (/* … */) are not stripped — they are unusual in import lines.
  const stripped = source.replace(/\/\/[^\n]*/g, "");

  // Pattern 1: static imports/exports with an optional "... from" clause
  //   import …from "X"  |  import "X"  |  export … from "X"
  const staticRe = /(?:import|export)\s+(?:[^"'\n;]*?\s+from\s+)?["']([^"']+)["']/g;

  // Pattern 2: dynamic import("X") and require("X")
  const dynamicRe = /(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)/g;

  for (const re of [staticRe, dynamicRe]) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(stripped)) !== null) {
      const specifier = m[1].toLowerCase();
      for (const forbidden of FORBIDDEN) {
        // Match as a path segment so "openai/client" hits "openai" but
        // "@supabase/supabase-js" does not hit "supabase".
        if (
          specifier === forbidden ||
          specifier.startsWith(forbidden + "/") ||
          specifier.includes("/" + forbidden + "/") ||
          specifier.startsWith("npm:" + forbidden) ||
          specifier.startsWith("jsr:" + forbidden)
        ) {
          return forbidden;
        }
      }
    }
  }
  return null;
}

// ---------------------------------------------------------------------------
// Helper: recursively collect all .ts files (excluding .test.ts)
// ---------------------------------------------------------------------------
async function collectSourceFiles(dir: string): Promise<string[]> {
  const results: string[] = [];
  for await (const entry of Deno.readDir(dir)) {
    const fullPath = `${dir}/${entry.name}`;
    if (entry.isDirectory) {
      results.push(...await collectSourceFiles(fullPath));
    } else if (
      entry.isFile &&
      entry.name.endsWith(".ts") &&
      !entry.name.endsWith(".test.ts")
    ) {
      results.push(fullPath);
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Tree scan: no forbidden imports anywhere in supabase/functions/
// ---------------------------------------------------------------------------
Deno.test(
  "invariant: no LLM model-SDK imports in supabase/functions/ source files",
  async () => {
    // This file lives in supabase/functions/_shared/
    // "../" goes up to supabase/functions/ on POSIX (Deno's primary platform).
    const functionsRoot = new URL("../", import.meta.url).pathname;

    const files = await collectSourceFiles(functionsRoot);
    // Must find at least the known source files so we know the scan ran.
    assertNotEquals(
      files.length,
      0,
      "No .ts files found — check functionsRoot path",
    );

    const violations: string[] = [];
    for (const file of files) {
      const source = await Deno.readTextFile(file);
      const hit = findForbiddenImport(source);
      if (hit !== null) {
        violations.push(`${file}: forbidden specifier "${hit}"`);
      }
    }

    assertEquals(
      violations,
      [],
      `LLM SDK imports found in trading path:\n${violations.join("\n")}`,
    );
  },
);

// ---------------------------------------------------------------------------
// Unit tests for findForbiddenImport helper
// ---------------------------------------------------------------------------

Deno.test("findForbiddenImport: clean import returns null", () => {
  assertEquals(findForbiddenImport(`import { foo } from "./foo.ts";`), null);
  assertEquals(
    findForbiddenImport(`import { createClient } from "@supabase/supabase-js";`),
    null,
  );
  assertEquals(findForbiddenImport(`import { assertEquals } from "@std/assert";`), null);
});

Deno.test("findForbiddenImport: catches 'openai' specifier", () => {
  assertNotEquals(findForbiddenImport(`import OpenAI from "openai";`), null);
  assertNotEquals(
    findForbiddenImport(`import { OpenAI } from "openai/client";`),
    null,
  );
  assertNotEquals(
    findForbiddenImport(`const o = await import("openai");`),
    null,
  );
});

Deno.test("findForbiddenImport: catches '@anthropic-ai/sdk' specifier", () => {
  assertNotEquals(
    findForbiddenImport(`import Anthropic from "@anthropic-ai/sdk";`),
    null,
  );
  assertNotEquals(
    findForbiddenImport(`import { Anthropic } from "anthropic";`),
    null,
  );
});

Deno.test("findForbiddenImport: forbidden word in a line comment does not trigger", () => {
  // The word "anthropic" appears only in a comment — not an import specifier.
  const source = `
// This module does NOT use the anthropic SDK.
// See CLAUDE.md invariant: no LLM in the trading path.
import { createClient } from "@supabase/supabase-js";
`;
  assertEquals(findForbiddenImport(source), null);
});

Deno.test("findForbiddenImport: catches langchain specifier", () => {
  assertNotEquals(
    findForbiddenImport(`import { ChatOpenAI } from "langchain/chat_models/openai";`),
    null,
  );
});

Deno.test("findForbiddenImport: catches npm:-prefixed specifier", () => {
  assertNotEquals(
    findForbiddenImport(`import OpenAI from "npm:openai";`),
    null,
  );
});
