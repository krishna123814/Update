// Ek DO instance = ek symbol (spot BTCUSDT ho ya kisi strike ka option
// symbol jaisa "BTC-260808-65000-C"). index.ts har symbol ke liye alag
// Durable Object route karta hai (idFromName(symbol)), isliye yahan
// symbol hardcode nahi karna — jo bhi client se query param mein aaya
// wahi is DO ka "apna" symbol ban jaata hai.

export class BTCDepthRelay {
  state: DurableObjectState;
  binanceSocket: WebSocket | null = null;
  symbol: string | null = null;

  constructor(state: DurableObjectState, _env: unknown) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("Expected a websocket upgrade request", {
        status: 400,
      });
    }

    const url = new URL(request.url);
    const symbol = url.searchParams.get("symbol");
    if (!symbol) {
      return new Response("Missing ?symbol= query param", { status: 400 });
    }
    this.symbol = symbol.toLowerCase();

    await this.ensureBinanceConnection();

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    // Hibernation API: DO idle ho sakta hai bina client connection tode.
    this.state.acceptWebSocket(server, ["client"]);

    return new Response(null, { status: 101, webSocket: client });
  }

  // Binance options depth stream se connection banata hai agar pehle se
  // open nahi hai. Symbol format: BINANCE options symbol as-is
  // (e.g. "BTC-260808-65000-C") — options stream lowercase leta hai.
  async ensureBinanceConnection(): Promise<void> {
    if (this.binanceSocket && this.binanceSocket.readyState === WebSocket.OPEN) {
      return;
    }
    if (!this.symbol) return;

    // NOTE: Cloudflare Workers mein outbound WS-upgrade fetch ke liye URL
    // scheme "https://" hona chahiye, "wss://" nahi — "wss://" silently
    // fail ho jaata hai (resp.webSocket hamesha null milta hai).
    const binanceUrl = `https://nbstream.binance.com/eoptions/ws/${this.symbol}@depth@100ms`;

    const resp = await fetch(binanceUrl, {
      headers: { Upgrade: "websocket" },
    });

    const ws = (resp as unknown as { webSocket: WebSocket | null }).webSocket;
    if (!ws) {
      throw new Error(
        `Binance ne websocket upgrade nahi diya (status=${resp.status})`
      );
    }

    ws.accept();
    this.binanceSocket = ws;

    ws.addEventListener("message", (event: MessageEvent) => {
      this.broadcast(event.data as string);
    });

    const cleanup = () => {
      this.binanceSocket = null;
    };
    ws.addEventListener("close", cleanup);
    ws.addEventListener("error", cleanup);
  }

  // Ek Binance message ko sabhi connected browser clients ko bhejta hai.
  broadcast(data: string): void {
    const clients = this.state.getWebSockets("client");
    for (const ws of clients) {
      try {
        ws.send(data);
      } catch {
        // socket band ho chuka — runtime khud hi cleanup kar dega
      }
    }
  }

  // Client se koi message aaye to abhi kuch nahi karna (sirf listen karte hain).
  async webSocketMessage(_ws: WebSocket, _message: string): Promise<void> {}

  async webSocketClose(
    _ws: WebSocket,
    _code: number,
    _reason: string
  ): Promise<void> {
    // Agar sab clients disconnect ho jaayein to Binance socket khula rehne do —
    // agla client (same strike) aayega to turant data milega.
  }

  async webSocketError(_ws: WebSocket): Promise<void> {}
}
