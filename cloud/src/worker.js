// Cloudflare entry point for Mtrini Cloud.
import { handle } from "./core.js";

export { Bridge } from "./bridge.js";

export default {
  fetch(request, env) {
    return handle(request, env, {
      db: env.DB,
      fetch: (url, init) => fetch(url, init),
      bridge: (userId) => env.BRIDGE.get(env.BRIDGE.idFromName(userId)),
    });
  },
};
