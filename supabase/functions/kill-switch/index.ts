import { handleKillSwitch } from "./handler.ts";

Deno.serve((req) => handleKillSwitch(req));
