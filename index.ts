import { BTCDepthRelay } from "./relay";

export { BTCDepthRelay };

interface Env {
  RELAY: DurableObjectNamespace;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (url.pathname === "/ws") {
      // Ek hi Durable Object instance — sabhi clients isi ek "room" mein
      // connect karte hain, taki Binance ka connection bhi ek hi rahe.
      const id = env.RELAY.idFromName("btcusdt-depth");
      const stub = env.RELAY.get(id);
      return stub.fetch(request);
    }

    return new Response(
      "BTCUSDT order book relay. Connect via wss://<your-worker>/ws",
      { status: 200 }
    );
  },
};
