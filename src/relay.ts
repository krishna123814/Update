// Binance depth stream ka URL. Chahe to @depth20@100ms (top-20, 100ms) use karo,
// ya sirf @depth (full diff stream, thoda zyada heavy).
const BINANCE_URL = "wss://stream.binance.com:9443/ws/btcusdt@depth20@100ms";

export class BTCDepthRelay {
  state: DurableObjectState;
  binanceSocket: WebSocket | null = null;

  constructor(state: DurableObjectState, _env: unknown) {
    this.state = state;
  }

  async fetch(request: Request): Promise<Response> {
    if (request.headers.get("Upgrade") !== "websocket") {
      return new Response("Expected a websocket upgrade request", {
        status: 400,
      });
    }

    await this.ensureBinanceConnection();

    const pair = new WebSocketPair();
    const [client, server] = Object.values(pair);

    // Hibernation API: DO idle ho sakta hai bina client connection tode.
    this.state.acceptWebSocket(server, ["client"]);

    return new Response(null, { status: 101, webSocket: client });
  }

  // Binance se connection banata hai agar pehle se open nahi hai.
  async ensureBinanceConnection(): Promise<void> {
    if (this.binanceSocket && this.binanceSocket.readyState === WebSocket.OPEN) {
      return;
    }

    const resp = await fetch(BINANCE_URL, {
      headers: { Upgrade: "websocket" },
    });

    const ws = (resp as unknown as { webSocket: WebSocket | null }).webSocket;
    if (!ws) {
      throw new Error("Binance ne websocket upgrade nahi diya");
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
    // agla client aayega to turant data milega, reconnect ka wait nahi karna padega.
  }

  async webSocketError(_ws: WebSocket): Promise<void> {}
}
