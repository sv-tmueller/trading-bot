import { handlePanic } from "./handler.ts";

Deno.serve((req) => handlePanic(req));
