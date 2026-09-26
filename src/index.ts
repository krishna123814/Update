import { BTCDepthRelay } from "./relay";

export { BTCDepthRelay };

interface Env {
  RELAY: DurableObjectNamespace;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    // Debug endpoint — normal HTTP GET (WebSocket nahi), seedha browser mein
    // khol ke exact Binance response (status/headers/body) dekh sakte ho.
    // Example: https://<worker>/debug?symbol=BTC-260927-84000-C
    if (url.pathname === "/debug") {
      const symbol = (url.searchParams.get("symbol") || "btc-260927-84000-c").toLowerCase();
      const binanceUrl = `https://nbstream.binance.com/eoptions/ws/${symbol}@depth@100ms`;
      try {
        const resp = await fetch(binanceUrl, {
          headers: { Upgrade: "websocket" },
        });
        const gotWebSocket = !!(resp as unknown as { webSocket: WebSocket | null }).webSocket;
        let body = "(no body read)";
        if (!gotWebSocket) {
          try {
            body = (await resp.text()).slice(0, 2000);
          } catch {
            body = "(could not read body)";
          }
        }
        return new Response(
          JSON.stringify(
            {
              requestedUrl: binanceUrl,
              httpStatus: resp.status,
              httpStatusText: resp.statusText,
              gotWebSocket,
              responseHeaders: Object.fromEntries(resp.headers.entries()),
              body,
            },
            null,
            2
          ),
          {
            headers: {
              "content-type": "application/json",
              "Access-Control-Allow-Origin": "*",
            },
          }
        );
      } catch (e: unknown) {
        const err = e as { name?: string; message?: string };
        return new Response(
          JSON.stringify(
            {
              requestedUrl: binanceUrl,
              fetchThrew: true,
              errorName: err?.name || "Error",
              errorMessage: err?.message || String(e),
            },
            null,
            2
          ),
          {
            status: 500,
            headers: {
              "content-type": "application/json",
              "Access-Control-Allow-Origin": "*",
            },
          }
        );
      }
    }

    if (url.pathname === "/ws") {
      const symbol = url.searchParams.get("symbol");
      if (!symbol) {
        return new Response("Missing ?symbol= query param", { status: 400 });
      }

      // Har symbol (strike) ka apna Durable Object instance — taaki ek
      // strike ka Binance connection doosre strike se bilkul alag rahe.
      const id = env.RELAY.idFromName(symbol.toLowerCase());
      const stub = env.RELAY.get(id);
      return stub.fetch(request);
    }

    return new Response(
      "BTCUSDT / options depth relay. Connect via wss://<worker>/ws?symbol=<symbol>. Debug via /debug?symbol=<symbol>",
      { status: 200 }
    );
  },
};
