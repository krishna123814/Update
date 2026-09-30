export default {
  async fetch(req, env) {
    if (!env.DAV_USER || !env.DAV_PASS || !env.HF_TOKEN || !env.HF_ORIGIN) {
      return new Response("Worker secrets missing", { status: 500 });
    }
    const want = "Basic " + btoa(env.DAV_USER + ":" + env.DAV_PASS);
    if (req.headers.get("Authorization") !== want) {
      return new Response("Unauthorized", {
        status: 401,
        headers: { "WWW-Authenticate": 'Basic realm="dav"' },
      });
    }
    const u = new URL(req.url);
    const target = new URL(u.pathname + u.search, env.HF_ORIGIN);
    const h = new Headers(req.headers);
    h.set("Authorization", "Bearer " + env.HF_TOKEN);
    const dest = h.get("Destination");
    if (dest) {
      h.set("Destination", new URL(new URL(dest).pathname, env.HF_ORIGIN).toString());
    }
    return fetch(target, { method: req.method, headers: h, body: req.body });
  },
};
