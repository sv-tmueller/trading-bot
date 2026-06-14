/**
 * Invariant enforcement: "No LLM in the trading path"
 *
 * Scans every non-test .ts file under supabase/functions/ and fails if any
 * forbidden model-SDK import specifier appears. Enforces CLAUDE.md Architectural
 * invariant #1. See docs/superpowers/specs/2026-06-14-invariant-enforcement-in-template-model-design.md
 *
 * THREAT MODEL:
 * This guard catches ACCIDENTAL / normal introduction of a model SDK into the
 * trading path (Layer 1, "No LLM in the trading path"). It is NOT proof against
 * deliberate obfuscation (e.g. `import("op"+"enai")`, unicode escapes) — that
 * is owned by Layer 2 (the reviewer's invariant check) and the fact that this
 * is first-party code.
 */
import { assertEquals, assertNotEquals } from "@std/assert";

// ---------------------------------------------------------------------------
// Forbidden stems (case-insensitive substring match on the extracted specifier)
// ---------------------------------------------------------------------------
const FORBIDDEN_STEMS = [
  "anthropic",
  "openai",
  "cohere",
  "mistral",
  "generative",
  "genai",
  "langchain",
];

/**
 * Extract module specifiers from an import / export / require expression and
 * test each against the forbidden stems. Returns the matched forbidden stem,
 * or null if the source is clean.
 *
 * Matches:
 *   import … from "X"      (named / default / namespace import, including multi-line)
 *   export … from "X"      (re-export)
 *   import "X"              (side-effect import)
 *   import("X")             (dynamic import)
 *   require("X")            (CommonJS)
 * Single and double quoted.  Does NOT match specifiers that appear only inside
 * comments (a forbidden word in "// comment" prose is not an import statement).
 *
 * Decision logic per extracted specifier:
 *   1. If the specifier starts with "." or "/" → first-party local path → NOT forbidden.
 *   2. Otherwise, lowercase it and flag as forbidden if it CONTAINS any forbidden STEM.
 *      (Optionally strip leading npm:/jsr:/scheme://host/ and trailing ?query/#fragment
 *      for clarity, but the substring test works regardless.)
 */
export function findForbiddenImport(source: string): string | null {
  // Pattern 1: static imports/exports with an optional "... from" clause.
  // [^"';]* (no \n restriction) allows multi-line { … } clauses.
  //   import …from "X"  |  import "X"  |  export … from "X"
  const staticRe = /(?:import|export)\s+(?:[^"';]*?\s+from\s+)?["']([^"']+)["']/g;

  // Pattern 2: dynamic import("X") and require("X")
  const dynamicRe = /(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)/g;

  for (const re of [staticRe, dynamicRe]) {
    let m: RegExpExecArray | null;
    while ((m = re.exec(source)) !== null) {
      const raw = m[1];

      // Step 1: first-party local path → never forbidden
      if (raw.startsWith(".") || raw.startsWith("/")) {
        continue;
      }

      // Step 2: substring-stem test (case-insensitive)
      const normalized = raw.toLowerCase();
      for (const stem of FORBIDDEN_STEMS) {
        if (normalized.includes(stem)) {
          return stem;
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
// Unit tests: CAUGHT (findForbiddenImport returns non-null)
// ---------------------------------------------------------------------------

Deno.test("findForbiddenImport CAUGHT: bare openai import", () => {
  assertNotEquals(findForbiddenImport(`import x from "openai"`), null);
});

Deno.test("findForbiddenImport CAUGHT: npm:openai", () => {
  assertNotEquals(findForbiddenImport(`import x from "npm:openai"`), null);
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/openai", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "https://esm.sh/openai"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/openai@4", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "https://esm.sh/openai@4"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/openai@4/index.mjs", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "https://esm.sh/openai@4/index.mjs"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: npm:openai@4/client", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "npm:openai@4/client"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/openai?bundle", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "https://esm.sh/openai?bundle"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: @anthropic-ai/sdk", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "@anthropic-ai/sdk"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: npm:@anthropic-ai/sdk", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "npm:@anthropic-ai/sdk"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: jsr:@anthropic-ai/sdk@0.20.0", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "jsr:@anthropic-ai/sdk@0.20.0"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: @google/generative-ai", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "@google/generative-ai"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/@google/generative-ai@1/index", () => {
  assertNotEquals(
    findForbiddenImport(
      `import x from "https://esm.sh/@google/generative-ai@1/index"`,
    ),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: @google/genai", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "@google/genai"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: cohere-ai", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "cohere-ai"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: @mistralai/mistralai", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "@mistralai/mistralai"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: @langchain/core", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "@langchain/core"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: langchain", () => {
  assertNotEquals(
    findForbiddenImport(`import x from "langchain"`),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: https://esm.sh/langchain@0.1.0/chat_models", () => {
  assertNotEquals(
    findForbiddenImport(
      `import x from "https://esm.sh/langchain@0.1.0/chat_models"`,
    ),
    null,
  );
});

Deno.test("findForbiddenImport CAUGHT: multi-line import", () => {
  const source = `import {\n  OpenAI,\n} from "openai"`;
  assertNotEquals(findForbiddenImport(source), null);
});

// ---------------------------------------------------------------------------
// Unit tests: NOT CAUGHT (findForbiddenImport returns null)
// ---------------------------------------------------------------------------

Deno.test("findForbiddenImport NOT caught: ./regime.ts", () => {
  assertEquals(findForbiddenImport(`import x from "./regime.ts"`), null);
});

Deno.test("findForbiddenImport NOT caught: ./openai-helper.ts", () => {
  assertEquals(
    findForbiddenImport(`import x from "./openai-helper.ts"`),
    null,
  );
});

Deno.test("findForbiddenImport NOT caught: ../shared/num.ts", () => {
  assertEquals(
    findForbiddenImport(`import x from "../shared/num.ts"`),
    null,
  );
});

Deno.test("findForbiddenImport NOT caught: jsr:@supabase/supabase-js@^2.45.0", () => {
  assertEquals(
    findForbiddenImport(
      `import x from "jsr:@supabase/supabase-js@^2.45.0"`,
    ),
    null,
  );
});

Deno.test("findForbiddenImport NOT caught: @std/assert", () => {
  assertEquals(
    findForbiddenImport(`import { assertEquals } from "@std/assert"`),
    null,
  );
});

Deno.test("findForbiddenImport NOT caught: forbidden stem in plain comment (not import)", () => {
  // "openai" appears only in a prose comment — not an import specifier.
  const source = `
// This module does NOT use the openai SDK.
// See CLAUDE.md invariant: no LLM in the trading path.
import { createClient } from "@supabase/supabase-js";
`;
  assertEquals(findForbiddenImport(source), null);
});
