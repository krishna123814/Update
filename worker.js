export default {
  // Proxy (pehle jaisa, koi badlav nahi)
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

  // Naya: har 1 minute HF space ko ping (cron trigger)
  async scheduled(event, env, ctx) {
    if (!env.HF_TOKEN || !env.HF_ORIGIN) return;
    try {
      const res = await fetch(env.HF_ORIGIN, {
        method: "GET",
        headers: { Authorization: "Bearer " + env.HF_TOKEN },
      });
      console.log("HF ping status:", res.status);
    } catch (err) {
      console.log("HF ping failed:", String(err));
    }
  },
};
