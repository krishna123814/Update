"""
update_app.py  —  BankNifty & BTC Data Updater
================================================
Fyers (BankNifty) + Binance Public API (BTC)
Dono .gz files ko fetch, merge, resample karke download karo.
"""

import io
import gzip
import pickle
import hashlib
import datetime
import requests
import time

import numpy as np
import pandas as pd
import streamlit as st

# ══════════════════════════════════════════════════════════════
#  HARDCODED CREDENTIALS
# ══════════════════════════════════════════════════════════════
FYERS_APP_ID     = "PPGUYSDHX7-100"
FYERS_SECRET     = "RWKTJYZ2YI"
FYERS_CLIENT_ID  = "FAJ86844"
FYERS_PASSWORD   = "2552"
FYERS_REDIRECT   = "https://www.google.com"

GITHUB_TOKEN     = st.secrets["GITHUB_TOKEN"]
GITHUB_REPO      = "krishna123814/Update"
GITHUB_BRANCH    = "main"

BN_GZ_FILENAME   = "banknifty_all_tf.pkl.gz"
BTC_GZ_FILENAME  = "btc_all_tf.pkl.gz"

BN_SYMBOL        = "NSE:NIFTYBANK-INDEX"
BTC_SYMBOL       = "BTCUSDT"
BINANCE_BASE     = "https://api.binance.com/api/v3/klines"

IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))

# ══════════════════════════════════════════════════════════════
#  PAGE CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Data Updater",
    page_icon="🔄",
    layout="centered",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
#MainMenu, footer, header,
[data-testid="stToolbar"],
[data-testid="stDecoration"] { display:none !important }

body, .stApp { background: #0f1117; color: #e0e0e0; }

.card {
    background: #1a1d2e;
    border: 1px solid #2a2d3e;
    border-radius: 12px;
    padding: 20px 24px;
    margin-bottom: 16px;
}
.section-title {
    font-size: 13px;
    font-weight: 600;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #7c83a0;
    margin-bottom: 12px;
}
.badge-green  { background:#1a3a2a; color:#4caf87; padding:3px 10px; border-radius:20px; font-size:12px; }
.badge-orange { background:#3a2a1a; color:#f0a050; padding:3px 10px; border-radius:20px; font-size:12px; }
.badge-red    { background:#3a1a1a; color:#f05050; padding:3px 10px; border-radius:20px; font-size:12px; }
</style>
""", unsafe_allow_html=True)

st.markdown("## 🔄 Data Updater")
st.markdown("BankNifty (Fyers) · BTC (Binance) · GitHub se load · Local download")
st.divider()


# ══════════════════════════════════════════════════════════════
#  SESSION STATE
# ══════════════════════════════════════════════════════════════
for key in ["fyers_token", "bn_data", "btc_data", "bn_updated", "btc_updated"]:
    if key not in st.session_state:
        st.session_state[key] = None


# ══════════════════════════════════════════════════════════════
#  HELPERS — GZ LOAD / SAVE
# ══════════════════════════════════════════════════════════════
def gz_to_bytes(data_dict: dict) -> bytes:
    buf = io.BytesIO()
    with gzip.open(buf, "wb") as f:
        pickle.dump(data_dict, f)
    return buf.getvalue()


def bytes_to_dict(raw: bytes) -> dict:
    with gzip.open(io.BytesIO(raw), "rb") as f:
        return pickle.load(f)


# ══════════════════════════════════════════════════════════════
#  HELPERS — GITHUB DOWNLOAD
# ══════════════════════════════════════════════════════════════
def github_download(filename: str) -> bytes | None:
    """Download raw file bytes from GitHub repo."""
    url = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{filename}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}
    try:
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            return r.content
        st.error(f"GitHub download failed: {r.status_code} — {r.text[:200]}")
        return None
    except Exception as e:
        st.error(f"GitHub download error: {e}")
        return None


# ══════════════════════════════════════════════════════════════
#  HELPERS — RESAMPLE (rolling accumulate logic)
# ══════════════════════════════════════════════════════════════
def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """
    Standard pandas resample — left-closed, left-labeled.
    For n-day rules (3d/9d/27d) we use custom groupby below.
    """
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last"}
    return df.resample(rule, closed="left", label="left").agg(agg).dropna()


def resample_nd(df_1d: pd.DataFrame, n: int, anchor_ts: pd.Timestamp) -> pd.DataFrame:
    """
    Resample 1d DataFrame into n-day candles.
    Grouping anchored from anchor_ts (last closed candle start in existing data).
    Last group may be incomplete — that's fine, it stays as partial candle.
    """
    df = df_1d.copy().sort_index()
    # Count days from anchor
    days_since = (df.index - anchor_ts).days
    group_id   = days_since // n
    agg = df.groupby(group_id).agg(
        Open=("Open", "first"),
        High=("High", "max"),
        Low=("Low", "min"),
        Close=("Close", "last"),
    )
    # Map group_id back to first date of each group
    first_dates = df.groupby(group_id).apply(lambda x: x.index[0])
    agg.index   = first_dates.values
    agg.index.name = df.index.name or "datetime"
    return agg


# ══════════════════════════════════════════════════════════════
#  HELPERS — MERGE (last incomplete candle replace)
# ══════════════════════════════════════════════════════════════
def merge_df(old_df: pd.DataFrame, new_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge old + new DataFrames.
    Last row of old_df may be incomplete — drop it if new_df covers that timestamp.
    """
    if new_df is None or new_df.empty:
        return old_df
    if old_df is None or old_df.empty:
        return new_df

    # Drop last candle of old (may be partial) if new_df overlaps
    last_old_ts = old_df.index[-1]
    if last_old_ts in new_df.index or last_old_ts >= new_df.index[0]:
        old_df = old_df[old_df.index < new_df.index[0]]

    combined = pd.concat([old_df, new_df])
    combined = combined[~combined.index.duplicated(keep="last")]
    return combined.sort_index()


# ══════════════════════════════════════════════════════════════
#  FYERS AUTH — Step-by-step
# ══════════════════════════════════════════════════════════════
def fyers_get_access_token_from_url(google_url: str) -> str | None:
    """Extract auth_code from redirected Google URL, then get access token."""
    try:
        if "auth_code=" not in google_url:
            st.error("URL mein auth_code nahi mila.")
            return None
        auth_code = google_url.split("auth_code=")[1].split("&")[0]
    except Exception:
        st.error("URL parse nahi hua.")
        return None

    app_hash = hashlib.sha256(f"{FYERS_APP_ID}:{FYERS_SECRET}".encode()).hexdigest()
    payload  = {
        "grant_type":  "authorization_code",
        "appIdHash":   app_hash,
        "code":        auth_code,
    }
    try:
        r = requests.post(
            "https://api-t1.fyers.in/api/v3/validate-authcode",
            json=payload, timeout=15,
        ).json()
        if r.get("s") == "ok" and "access_token" in r:
            return r["access_token"]
        st.error(f"Token error: {r.get('message', r)}")
        return None
    except Exception as e:
        st.error(f"Token fetch error: {e}")
        return None


def fyers_auth_url() -> str:
    """Generate Fyers login URL."""
    from urllib.parse import quote
    return (
        f"https://api-t1.fyers.in/api/v3/generate-authcode"
        f"?client_id={FYERS_APP_ID}"
        f"&redirect_uri={quote(FYERS_REDIRECT)}"
        f"&response_type=code"
        f"&state=update_app"
    )


# ══════════════════════════════════════════════════════════════
#  FYERS DATA FETCH — with pagination
# ══════════════════════════════════════════════════════════════
FYERS_TF_MAP = {
    "5m":   5,
    "15m":  15,
    "45m":  45,
    "135m": 135,
    "1d":   "D",
}

def fyers_fetch_candles(
    access_token: str,
    symbol: str,
    resolution: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
) -> pd.DataFrame:
    """
    Fetch OHLC from Fyers with pagination.
    Fyers allows max 100 days per call for intraday.
    """
    headers = {"Authorization": f"{FYERS_APP_ID}:{access_token}"}
    all_rows = []

    # Chunk size: 100 days for intraday, 365 days for daily
    chunk_days = 100 if resolution != "D" else 365
    cur_from   = from_dt

    while cur_from < to_dt:
        cur_to = min(cur_from + datetime.timedelta(days=chunk_days), to_dt)
        params = {
            "symbol":     symbol,
            "resolution": str(resolution),
            "date_format": "1",
            "range_from": cur_from.strftime("%Y-%m-%d"),
            "range_to":   cur_to.strftime("%Y-%m-%d"),
            "cont_flag":  "1",
        }
        try:
            r = requests.get(
                "https://api-t1.fyers.in/data/history",
                headers=headers, params=params, timeout=20,
            ).json()
            candles = r.get("candles", [])
            if candles:
                all_rows.extend(candles)
        except Exception as e:
            st.warning(f"Fyers chunk error ({cur_from.date()} – {cur_to.date()}): {e}")

        cur_from = cur_to + datetime.timedelta(days=1)
        time.sleep(0.3)  # rate limit

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=["timestamp", "Open", "High", "Low", "Close", "Volume"])
    df["datetime"] = pd.to_datetime(df["timestamp"], unit="s", utc=True).dt.tz_convert(IST).dt.tz_localize(None)
    df = df.set_index("datetime")[["Open", "High", "Low", "Close"]]
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


# ══════════════════════════════════════════════════════════════
#  BINANCE DATA FETCH — with pagination
# ══════════════════════════════════════════════════════════════
BINANCE_INTERVAL = "1h"   # fetch 1h then resample to 160m / 8h etc.
# Actually Binance supports 1m,3m,5m,15m,30m,1h,2h,4h,6h,8h,12h,1d,3d,1w,1M
# 160m is NOT a standard Binance interval. We fetch 1h and resample.

def binance_fetch_candles(
    symbol: str,
    interval: str,
    from_dt: datetime.datetime,
    to_dt: datetime.datetime,
) -> pd.DataFrame:
    """
    Fetch OHLC from Binance public API with pagination (max 1000 per call).
    from_dt / to_dt are UTC-naive (treated as UTC).
    """
    all_rows = []
    cur_from_ms = int(from_dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)
    to_ms       = int(to_dt.replace(tzinfo=datetime.timezone.utc).timestamp() * 1000)

    while cur_from_ms < to_ms:
        params = {
            "symbol":    symbol,
            "interval":  interval,
            "startTime": cur_from_ms,
            "endTime":   to_ms,
            "limit":     1000,
        }
        try:
            r = requests.get(BINANCE_BASE, params=params, timeout=20)
            rows = r.json()
            if not rows or isinstance(rows, dict):
                break
            all_rows.extend(rows)
            # Last candle's close time + 1ms
            cur_from_ms = rows[-1][6] + 1
            if len(rows) < 1000:
                break
        except Exception as e:
            st.warning(f"Binance fetch error: {e}")
            break
        time.sleep(0.2)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows, columns=[
        "open_time","Open","High","Low","Close","Volume",
        "close_time","qav","num_trades","tbbav","tbqav","ignore"
    ])
    df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_localize(None)
    df = df.set_index("datetime")[["Open","High","Low","Close"]].astype(float)
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


# ══════════════════════════════════════════════════════════════
#  BANKNIFTY UPDATE LOGIC
# ══════════════════════════════════════════════════════════════
def update_banknifty(data: dict, access_token: str) -> dict:
    """
    Update all BankNifty timeframes.
    Base: 5m from Fyers → resample up.
    Higher TFs (3d/9d/27d): from 1d.
    """
    now_ist = datetime.datetime.now(IST).replace(tzinfo=None)

    # ── Fetch new 5m data ──
    last_5m = data["5m"].index[-1]
    st.write(f"  📥 5m fetch: {last_5m.date()} → today")
    new_5m = fyers_fetch_candles(
        access_token, BN_SYMBOL, 5,
        from_dt=last_5m - datetime.timedelta(days=1),
        to_dt=now_ist,
    )

    if new_5m.empty:
        st.warning("5m: koi nayi candles nahi mili.")
        return data

    # Market hours filter (9:15 – 15:30 IST)
    new_5m = new_5m[
        (new_5m.index.time >= datetime.time(9, 15)) &
        (new_5m.index.time <= datetime.time(15, 30))
    ]

    data["5m"] = merge_df(data["5m"], new_5m)
    st.write(f"  ✅ 5m updated → {len(data['5m'])} rows")

    # ── Resample 5m → 15m, 45m, 135m ──
    base_5m = data["5m"]

    for tf, minutes in [("15m", 15), ("45m", 45), ("135m", 135)]:
        rule = f"{minutes}min"
        resampled = resample_ohlc(base_5m, rule)
        # Filter market hours
        resampled = resampled[
            (resampled.index.time >= datetime.time(9, 15)) &
            (resampled.index.time <= datetime.time(15, 30))
        ]
        data[tf] = resampled
        st.write(f"  ✅ {tf} resampled → {len(data[tf])} rows")

    # ── Fetch 1d from Fyers ──
    last_1d = data["1d"].index[-1]
    st.write(f"  📥 1d fetch: {last_1d.date()} → today")
    new_1d = fyers_fetch_candles(
        access_token, BN_SYMBOL, "D",
        from_dt=last_1d - datetime.timedelta(days=5),
        to_dt=now_ist,
    )
    if not new_1d.empty:
        data["1d"] = merge_df(data["1d"], new_1d)
    st.write(f"  ✅ 1d updated → {len(data['1d'])} rows")

    # ── Resample 1d → 3d, 9d, 27d (Option B anchor) ──
    df_1d = data["1d"]
    for n, key in [(3, "3d"), (9, "9d"), (27, "27d")]:
        anchor = data[key].index[-1] if key in data and not data[key].empty else df_1d.index[0]
        data[key] = resample_nd(df_1d, n, anchor)
        st.write(f"  ✅ {key} resampled → {len(data[key])} rows")

    return data


# ══════════════════════════════════════════════════════════════
#  BTC UPDATE LOGIC
# ══════════════════════════════════════════════════════════════
def update_btc(data: dict) -> dict:
    """
    Update all BTC timeframes.
    Base: 1h from Binance → resample to 160m, 8h.
    1d from Binance directly → 3d, 9d, 27d.
    """
    now_utc = datetime.datetime.utcnow()

    # ── Fetch 1h data (for 160m and 8h) ──
    last_160m = data["160m"].index[-1]
    st.write(f"  📥 1h fetch (for 160m/8h): {last_160m.date()} → today")
    new_1h = binance_fetch_candles(
        BTC_SYMBOL, "1h",
        from_dt=last_160m - datetime.timedelta(days=2),
        to_dt=now_utc,
    )

    if not new_1h.empty:
        # Resample 1h → 160m
        new_160m = resample_ohlc(new_1h, "160min")
        data["160m"] = merge_df(data["160m"], new_160m)
        st.write(f"  ✅ 160m updated → {len(data['160m'])} rows")

        # Resample 1h → 8h
        new_8h = resample_ohlc(new_1h, "8h")
        data["8h"] = merge_df(data["8h"], new_8h)
        st.write(f"  ✅ 8h updated → {len(data['8h'])} rows")
    else:
        st.warning("1h: koi nayi candles nahi mili (160m/8h update skip).")

    # ── Fetch 1d data ──
    last_1d = data["1d"].index[-1]
    st.write(f"  📥 1d fetch: {last_1d.date()} → today")
    new_1d = binance_fetch_candles(
        BTC_SYMBOL, "1d",
        from_dt=last_1d - datetime.timedelta(days=5),
        to_dt=now_utc,
    )
    if not new_1d.empty:
        data["1d"] = merge_df(data["1d"], new_1d)
    st.write(f"  ✅ 1d updated → {len(data['1d'])} rows")

    # ── Resample 1d → 3d, 9d, 27d (Option B anchor) ──
    df_1d = data["1d"]
    for n, key in [(3, "3d"), (9, "9d"), (27, "27d")]:
        anchor = data[key].index[-1] if key in data and not data[key].empty else df_1d.index[0]
        data[key] = resample_nd(df_1d, n, anchor)
        st.write(f"  ✅ {key} resampled → {len(data[key])} rows")

    return data


# ══════════════════════════════════════════════════════════════
#  UI — SECTION 1: FYERS AUTH
# ══════════════════════════════════════════════════════════════
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">🔐 Fyers Login (BankNifty ke liye)</div>', unsafe_allow_html=True)

if st.session_state.fyers_token:
    st.markdown('<span class="badge-green">✓ Connected</span>', unsafe_allow_html=True)
    if st.button("Logout", key="fyers_logout"):
        st.session_state.fyers_token = None
        st.rerun()
else:
    login_url = fyers_auth_url()
    st.markdown(
        f'**Step 1:** [Yahan click karo → Fyers Login]({login_url})',
        unsafe_allow_html=True,
    )
    st.caption("Login hone ke baad Google page ka poora URL copy karke neeche paste karo.")
    google_url = st.text_input(
        "Step 2: Redirected Google URL paste karo",
        placeholder="https://www.google.com/?auth_code=eyJ...&state=...",
        key="google_url_input",
    )
    if st.button("🔑 Token Extract Karo", key="fyers_auth_btn"):
        if google_url.strip():
            with st.spinner("Token extract ho raha hai..."):
                tok = fyers_get_access_token_from_url(google_url.strip())
            if tok:
                st.session_state.fyers_token = tok
                st.success("✅ Fyers connected!")
                st.rerun()
        else:
            st.warning("URL paste karo pehle.")

st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  UI — SECTION 2: LOAD FILES FROM GITHUB
# ══════════════════════════════════════════════════════════════
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">📦 GitHub se Files Load Karo</div>', unsafe_allow_html=True)

col1, col2 = st.columns(2)

with col1:
    if st.button("📥 BankNifty Load", use_container_width=True):
        with st.spinner(f"{BN_GZ_FILENAME} download ho raha hai..."):
            raw = github_download(BN_GZ_FILENAME)
        if raw:
            st.session_state.bn_data = bytes_to_dict(raw)
            st.session_state.bn_updated = False
            bn_last = st.session_state.bn_data.get("5m", pd.DataFrame())
            last_dt = bn_last.index[-1] if not bn_last.empty else "?"
            st.success(f"✅ Loaded! Last 5m candle: {last_dt}")
        else:
            st.error("Download fail hua.")

with col2:
    if st.button("📥 BTC Load", use_container_width=True):
        with st.spinner(f"{BTC_GZ_FILENAME} download ho raha hai..."):
            raw = github_download(BTC_GZ_FILENAME)
        if raw:
            st.session_state.btc_data = bytes_to_dict(raw)
            st.session_state.btc_updated = False
            btc_last = st.session_state.btc_data.get("160m", pd.DataFrame())
            last_dt = btc_last.index[-1] if not btc_last.empty else "?"
            st.success(f"✅ Loaded! Last 160m candle: {last_dt}")
        else:
            st.error("Download fail hua.")

st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  UI — SECTION 3: UPDATE
# ══════════════════════════════════════════════════════════════
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">🔄 Update Karo</div>', unsafe_allow_html=True)

col3, col4 = st.columns(2)

with col3:
    bn_ready = st.session_state.bn_data is not None and st.session_state.fyers_token is not None
    if st.button(
        "🚀 BankNifty Update",
        use_container_width=True,
        disabled=not bn_ready,
    ):
        st.write("**BankNifty update shuru...**")
        with st.spinner("Fyers se data fetch ho raha hai..."):
            try:
                updated = update_banknifty(
                    st.session_state.bn_data,
                    st.session_state.fyers_token,
                )
                st.session_state.bn_data    = updated
                st.session_state.bn_updated = True
                st.success("✅ BankNifty update complete!")
            except Exception as e:
                st.error(f"Error: {e}")

    if not st.session_state.fyers_token:
        st.caption("⚠ Fyers login zaroori hai")
    elif st.session_state.bn_data is None:
        st.caption("⚠ Pehle BankNifty load karo")

with col4:
    btc_ready = st.session_state.btc_data is not None
    if st.button(
        "🚀 BTC Update",
        use_container_width=True,
        disabled=not btc_ready,
    ):
        st.write("**BTC update shuru...**")
        with st.spinner("Binance se data fetch ho raha hai..."):
            try:
                updated = update_btc(st.session_state.btc_data)
                st.session_state.btc_data    = updated
                st.session_state.btc_updated = True
                st.success("✅ BTC update complete!")
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state.btc_data is None:
        st.caption("⚠ Pehle BTC load karo")

st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  UI — SECTION 4: DATA INFO
# ══════════════════════════════════════════════════════════════
if st.session_state.bn_data or st.session_state.btc_data:
    st.markdown('<div class="card">', unsafe_allow_html=True)
    st.markdown('<div class="section-title">📊 Current Data Info</div>', unsafe_allow_html=True)

    if st.session_state.bn_data:
        st.markdown("**BankNifty**")
        bn_info = {}
        for tf in ["5m","15m","45m","135m","1d","3d","9d","27d"]:
            df = st.session_state.bn_data.get(tf)
            if df is not None and not df.empty:
                bn_info[tf] = f"{len(df)} rows | Last: {df.index[-1].strftime('%Y-%m-%d %H:%M')}"
        info_df = pd.DataFrame.from_dict(bn_info, orient="index", columns=["Info"])
        st.dataframe(info_df, use_container_width=True)

    if st.session_state.btc_data:
        st.markdown("**BTC**")
        btc_info = {}
        for tf in ["160m","8h","1d","3d","9d","27d"]:
            df = st.session_state.btc_data.get(tf)
            if df is not None and not df.empty:
                btc_info[tf] = f"{len(df)} rows | Last: {df.index[-1].strftime('%Y-%m-%d %H:%M')}"
        info_df2 = pd.DataFrame.from_dict(btc_info, orient="index", columns=["Info"])
        st.dataframe(info_df2, use_container_width=True)

    st.markdown('</div>', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  UI — SECTION 5: DOWNLOAD
# ══════════════════════════════════════════════════════════════
st.markdown('<div class="card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">⬇️ Download Updated Files</div>', unsafe_allow_html=True)
st.caption("Download karo → GitHub pe manually upload karo")

col5, col6 = st.columns(2)

with col5:
    if st.session_state.bn_data and st.session_state.bn_updated:
        bn_bytes = gz_to_bytes(st.session_state.bn_data)
        st.download_button(
            label="⬇️ banknifty_all_tf.pkl.gz",
            data=bn_bytes,
            file_name=BN_GZ_FILENAME,
            mime="application/gzip",
            use_container_width=True,
        )
        size_kb = len(bn_bytes) / 1024
        st.caption(f"Size: {size_kb:.1f} KB")
    elif st.session_state.bn_data and not st.session_state.bn_updated:
        st.markdown('<span class="badge-orange">Update karo pehle</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-red">Load nahi hua</span>', unsafe_allow_html=True)

with col6:
    if st.session_state.btc_data and st.session_state.btc_updated:
        btc_bytes = gz_to_bytes(st.session_state.btc_data)
        st.download_button(
            label="⬇️ btc_all_tf.pkl.gz",
            data=btc_bytes,
            file_name=BTC_GZ_FILENAME,
            mime="application/gzip",
            use_container_width=True,
        )
        size_kb = len(btc_bytes) / 1024
        st.caption(f"Size: {size_kb:.1f} KB")
    elif st.session_state.btc_data and not st.session_state.btc_updated:
        st.markdown('<span class="badge-orange">Update karo pehle</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge-red">Load nahi hua</span>', unsafe_allow_html=True)

st.markdown('</div>', unsafe_allow_html=True)

st.markdown("""
<div style="text-align:center; color:#3a3d4e; font-size:12px; margin-top:24px;">
    Download ke baad GitHub repo mein manually upload karo (same filename)
</div>
""", unsafe_allow_html=True)
