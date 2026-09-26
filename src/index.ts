import { BTCDepthRelay } from "./relay";

export { BTCDepthRelay };

interface Env {
  RELAY: DurableObjectNamespace;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

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
      "BTCUSDT / options depth relay. Connect via wss://<worker>/ws?symbol=<symbol>",
      { status: 200 }
    );
  },
};
