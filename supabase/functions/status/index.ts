import { handleStatus } from "./handler.ts";

Deno.serve((req) => handleStatus(req));
