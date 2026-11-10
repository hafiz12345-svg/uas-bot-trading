from http.server import BaseHTTPRequestHandler
import os, sys, json, time
from datetime import datetime, timezone
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from signal_strategy import signal, N_MASUK  # fungsi yang sama dengan backtest

BASE = "https://indodax.com"
PAIRS = ["BTCIDR", "ETHIDR", "XRPIDR"]
TF_SEC = 3600            # timeframe 1 jam
MAX_SPREAD_PCT = 2.0     # spread > 2% -> jangan buka posisi


# ---------- Redis (Upstash, lewat REST) ----------
def redis(*cmd):
    url = os.environ["KV_REST_API_URL"]
    token = os.environ["KV_REST_API_TOKEN"]
    r = requests.post(url, headers={"Authorization": f"Bearer {token}"},
                      json=list(cmd), timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def log(key, obj):
    redis("RPUSH", key, json.dumps(obj))


# ---------- Ambil data dengan retry terbatas ----------
def get_json(url, params=None, tries=3):
    err = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            if data:
                return data
            err = "respons kosong"
        except Exception as e:
            err = str(e)
        time.sleep(1)
    raise RuntimeError(f"gagal ambil data setelah {tries}x: {err}")


# ---------- Proses satu pasangan ----------
def proses_pair(pair, server_sec, state, waktu):
    hasil = {"pair": pair}

    # order book
    depth = get_json(f"{BASE}/api/depth/{pair.lower()}")
    if not depth.get("buy") or not depth.get("sell"):
        hasil.update(status="SKIP", alasan="order book kosong")
        return hasil
    bid = float(depth["buy"][0][0])
    ask = float(depth["sell"][0][0])
    spread = (ask - bid) / ask * 100
    hasil.update(bid=bid, ask=ask, spread_pct=round(spread, 4))

    # simpan snapshot order book (untuk estimasi spread)
    log("snapshots", {"waktu_utc": waktu, "pair": pair, "bid": bid, "ask": ask,
                      "spread_pct": spread,
                      "buy": depth["buy"][:20], "sell": depth["sell"][:20]})

    # candle
    candles = get_json(f"{BASE}/tradingview/history_v2",
                       {"symbol": pair, "tf": "60",
                        "from": server_sec - 48 * 3600, "to": server_sec})
    # buang candle yang belum tertutup (Time dalam detik)
    closed = sorted([b for b in candles if b["Time"] + TF_SEC <= server_sec],
                    key=lambda b: b["Time"])

    # validasi data
    if len(closed) < N_MASUK + 1:
        hasil.update(status="SKIP", alasan="candle kurang"); return hasil
    last = closed[-1]
    if server_sec - (last["Time"] + TF_SEC) > 2 * TF_SEC:
        hasil.update(status="SKIP", alasan="candle terakhir basi"); return hasil
    window = closed[-(N_MASUK + 1):]
    for i in range(1, len(window)):
        if window[i]["Time"] - window[i - 1]["Time"] != TF_SEC:
            hasil.update(status="SKIP", alasan="ada candle hilang"); return hasil
    if any(float(b["Close"]) <= 0 or float(b["Volume"]) <= 0 for b in window):
        hasil.update(status="SKIP", alasan="harga atau volume nol"); return hasil
    if spread > MAX_SPREAD_PCT:
        hasil.update(status="SKIP", alasan="spread lebih dari 2%"); return hasil

    # idempotency: satu candle hanya diproses sekali
    if state.get(pair) == last["Time"]:
        hasil.update(status="SUDAH_DIPROSES", candle=last["Time"]); return hasil

    # sinyal (versi 1: belum ada posisi, belum ada order)
    closes = [float(b["Close"]) for b in closed]
    sinyal = signal(closes, False)
    state[pair] = last["Time"]
    hasil.update(status="OK", candle=last["Time"], close=closes[-1], sinyal=sinyal)
    return hasil


# ---------- Endpoint ----------
class handler(BaseHTTPRequestHandler):
    def _balas(self, kode, obj):
        self.send_response(kode)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    def do_GET(self):
        secret = os.environ.get("CRON_SECRET", "")
        if not secret or self.headers.get("Authorization", "") != f"Bearer {secret}":
            self._balas(401, {"error": "unauthorized"})
            return

        waktu = datetime.now(timezone.utc).isoformat()
        catatan = {"waktu_utc": waktu, "hasil": [], "error": []}
        try:
            # kill switch: env var ATAU flag di Redis
            if os.environ.get("KILL_SWITCH") == "1" or redis("GET", "kill_switch") == "1":
                catatan["kill_switch"] = True
                log("calls", catatan)
                self._balas(200, catatan)
                return

            server_sec = int(get_json(f"{BASE}/api/server_time")["server_time"]) // 1000
            raw = redis("GET", "state")
            state = json.loads(raw) if raw else {}

            for pair in PAIRS:
                try:
                    catatan["hasil"].append(proses_pair(pair, server_sec, state, waktu))
                except Exception as e:
                    catatan["error"].append({"pair": pair, "pesan": str(e)})
                time.sleep(0.4)

            redis("SET", "state", json.dumps(state))
        except Exception as e:
            catatan["error"].append({"pesan": str(e)})

        try:
            log("calls", catatan)
        except Exception:
            pass
        self._balas(200, catatan)
