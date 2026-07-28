import { handleHourlyCheck } from "./handler.ts";

Deno.serve((req) => handleHourlyCheck(req));
