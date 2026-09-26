# BTCUSDT Order Book Relay (Cloudflare Worker + Durable Object)

## Deploy karne ke steps

```bash
cd btcusdt-relay
npm init -y
npm install -D wrangler typescript @cloudflare/workers-types
wrangler login          # browser khulega, Cloudflare account se login karo
wrangler deploy
```

Deploy hone ke baad ek URL milega, jaise:
`https://btcusdt-relay.<tumhara-subdomain>.workers.dev`

## Tumhare `chart.html` mein use karna

```javascript
const ws = new WebSocket("wss://btcusdt-relay.<tumhara-subdomain>.workers.dev/ws");

ws.onmessage = (event) => {
  const depth = JSON.parse(event.data);
  // depth.bids -> [[price, qty], ...]
  // depth.asks -> [[price, qty], ...]
  updateOrderBookUI(depth);
};

ws.onopen = () => console.log("Order book stream connected");
ws.onclose = () => console.log("Disconnected — browser khud retry try kar sakta hai");
```

## Kaise kaam karta hai

- Pehla client jab `/ws` pe connect karta hai, Durable Object Binance se ek connection kholta hai.
- Baad ke sab clients usi ek Binance connection ka data share karte hain (fan-out) — Binance pe multiple connections nahi khultin.
- Sabhi clients disconnect ho jaayein tab bhi Binance socket khula rehta hai, taki agla client turant data paaye.

## Agar depth stream ka format change karna ho

`src/relay.ts` mein `BINANCE_URL` line change karo:
- `@depth20@100ms` — top 20 levels, 100ms updates (halka)
- `@depth` — full diff stream (zyada data, manual order book maintain karna padega)
