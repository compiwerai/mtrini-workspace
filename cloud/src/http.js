// Shared response helpers and database shortcuts for the Mtrini Cloud routes.

// The phone app calls the JSON API from its own origin. Auth is a bearer token (never a cookie),
// so allowing any origin exposes nothing a script couldn't already do with the token.
export const CORS = { "access-control-allow-origin": "*", "access-control-allow-headers": "authorization, content-type",
  "access-control-allow-methods": "GET, POST, PUT, DELETE, OPTIONS", "access-control-max-age": "86400" };
export const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...CORS } });
export const err = (status, code, message, extra = {}) => json({ error: { code, message }, ...extra }, status);

export const one = (db, sql, ...args) => db.prepare(sql).bind(...args).first();
export const all = async (db, sql, ...args) => (await db.prepare(sql).bind(...args).all()).results || [];
export const run = (db, sql, ...args) => db.prepare(sql).bind(...args).run();

export async function body(request) {
  try { return await request.json(); } catch { return {}; }
}
