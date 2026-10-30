// Cloudflare entry point: the request handler plus one Durable Object that keeps the daily
// counters, so every request sees the same totals.
import { DurableObject } from "cloudflare:workers";

import { handle, Limiter } from "./core.js";

export class LimiterObject extends DurableObject {
  constructor(ctx, env) {
    super(ctx, env);
    this.limiter = new Limiter(ctx.storage, env);
  }

  reserve(user, ip) {
    return this.limiter.reserve(user, ip);
  }

  record(user, ip, cost) {
    return this.limiter.record(user, ip, cost);
  }
}

export default {
  async fetch(request, env, ctx) {
    const stub = env.LIMITER.get(env.LIMITER.idFromName("global"));
    return handle(request, env, {
      limiter: stub,
      fetch: (url, init) => fetch(url, init),
      waitUntil: (p) => ctx.waitUntil(p),
    });
  },
};
