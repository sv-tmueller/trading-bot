import { handleDailyCheck } from "./handler.ts";

Deno.serve((req) => handleDailyCheck(req));
