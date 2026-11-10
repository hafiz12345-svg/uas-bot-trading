from http.server import BaseHTTPRequestHandler
import os, sys, json, time, math
from datetime import datetime, timezone
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from signal_strategy import signal, N_MASUK  # fungsi yang sama dengan backtest

BASE = "https://indodax.com"
PAIRS = ["BTCIDR", "ETHIDR", "XRPIDR"]
TF_SEC = 3600

# ===== PARAMETER (dibekukan saat freeze) =====
MODAL = 100_000_000        # modal virtual (Rp)
FEE_TAKER = 0.003          # 0,3% (sementara; samakan dengan angka all-in resmi sebelum freeze)
MIN_ORDER = 25_000         # minimum order (Rp)
MAX_POSITIONS = 3          # maksimum posisi terbuka
MAX_POS_FRAC = 0.30        # maksimum 30% equity per posisi
DAILY_LOSS_LIMIT = 0.03    # rugi harian > 3% -> stop beli sampai besok (hari WIB)
MAX_SPREAD_PCT = 2.0       # spread > 2% -> jangan buka posisi


# ---------- Redis (Upstash REST) ----------
def redis(*cmd):
    r = requests.post(os.environ["KV_REST_API_URL"],
                      headers={"Authorization": f"Bearer {os.environ['KV_REST_API_TOKEN']}"},
                      json=list(cmd), timeout=10)
    r.raise_for_status()
    return r.json().get("result")


def log(key, obj):
    redis("RPUSH", key, json.dumps(obj))


# ---------- Ambil data (retry terbatas) ----------
def get_json(url, params=None, tries=3):
    err = None
    for _ in range(tries):
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


def ambil_book(pair):
    d = get_json(f"{BASE}/api/depth/{pair.lower()}")
    if not d.get("buy") or not d.get("sell"):
        return None
    bids = sorted([(float(p), float(v)) for p, v in d["buy"]], reverse=True)
    asks = sorted([(float(p), float(v)) for p, v in d["sell"]])
    bid, ask = bids[0][0], asks[0][0]
    return {"bids": bids, "asks": asks, "bid": bid, "ask": ask,
            "spread": (ask - bid) / ask * 100, "raw": d}


# ---------- Simulasi fill di order book ----------
def floor8(x):
    return math.floor(x * 1e8) / 1e8


def fill_beli(asks, budget):
    """budget = total uang keluar (termasuk fee). Telusuri level ask."""
    sisa = budget / (1 + FEE_TAKER)
    qty = spent = 0.0
    level = 0
    for p, v in asks:
        if sisa <= 1e-9:
            break
        ambil = min(v, sisa / p)
        qty += ambil
        spent += ambil * p
        sisa -= ambil * p
        level += 1
    if qty <= 0:
        return None
    avg = spent / qty
    qty = floor8(qty)
    notional = avg * qty
    return {"qty": qty, "avg": avg, "notional": notional,
            "fee": notional * FEE_TAKER, "level": level}


def fill_jual(bids, qty):
    sisa = qty
    got = terjual = 0.0
    level = 0
    for p, v in bids:
        if sisa <= 1e-12:
            break
        ambil = min(v, sisa)
        got += ambil * p
        terjual += ambil
        sisa -= ambil
        level += 1
    if terjual <= 0:
        return None
    return {"qty": terjual, "avg": got / terjual, "notional": got,
            "fee": got * FEE_TAKER, "level": level, "sisa": sisa}


# ---------- Equity: posisi dinilai di best bid ----------
def hitung_equity(st, books):
    total = st["cash"]
    for pair, pos in st["pos"].items():
        b = books.get(pair)
        bid = b["bid"] if b else st["lastbid"].get(pair, 0)
        total += pos["qty"] * bid
    return total


def hari_wib(server_sec):
    return datetime.fromtimestamp(server_sec + 7 * 3600, timezone.utc).strftime("%Y-%m-%d")


# ---------- Proses satu pasangan ----------
def proses_pair(pair, server_sec, st, books, waktu, halted, equity):
    hasil = {"pair": pair}
    book = books.get(pair)
    if book is None:
        hasil.update(status="SKIP", alasan="order book kosong atau gagal")
        return hasil
    bid, ask, spread = book["bid"], book["ask"], book["spread"]
    hasil.update(bid=bid, ask=ask, spread_pct=round(spread, 4))

    candles = get_json(f"{BASE}/tradingview/history_v2",
                       {"symbol": pair, "tf": "60",
                        "from": server_sec - 48 * 3600, "to": server_sec})
    closed = sorted([b for b in candles if b["Time"] + TF_SEC <= server_sec],
                    key=lambda b: b["Time"])  # buang candle yang belum tertutup

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

    # idempotency: satu candle hanya diproses sekali
    if st["last"].get(pair) == last["Time"]:
        hasil.update(status="SUDAH_DIPROSES", candle=last["Time"]); return hasil

    closes = [float(b["Close"]) for b in closed]
    harga_sinyal = closes[-1]
    punya = pair in st["pos"]
    sinyal = signal(closes, punya)
    st["last"][pair] = last["Time"]
    hasil.update(status="OK", candle=last["Time"], close=harga_sinyal, sinyal=sinyal)

    if sinyal == "BUY":
        if halted:
            hasil["aksi"] = "BUY ditolak: daily loss limit"
        elif spread > MAX_SPREAD_PCT:
            hasil["aksi"] = "BUY ditolak: spread lebih dari 2%"
        elif len(st["pos"]) >= MAX_POSITIONS:
            hasil["aksi"] = "BUY ditolak: batas posisi"
        else:
            budget = min(MAX_POS_FRAC * equity, st["cash"])
            if budget < MIN_ORDER * (1 + FEE_TAKER):
                hasil["aksi"] = "BUY ditolak: di bawah minimum order"
            else:
                f = fill_beli(book["asks"], budget)
                if f is None or f["notional"] < MIN_ORDER:
                    hasil["aksi"] = "BUY ditolak: di bawah minimum order"
                else:
                    st["cash"] -= f["notional"] + f["fee"]
                    st["pos"][pair] = {"qty": f["qty"], "cost": f["notional"] + f["fee"]}
                    order = {"waktu_utc": waktu, "pair": pair, "sisi": "BUY", "qty": f["qty"],
                             "best_bid": bid, "best_ask": ask, "harga_fill": f["avg"],
                             "notional": f["notional"], "fee": f["fee"],
                             "harga_sinyal": harga_sinyal,
                             "selisih_pct": (f["avg"] - harga_sinyal) / harga_sinyal * 100,
                             "level_dipakai": f["level"]}
                    log("orders", order)
                    hasil["aksi"] = "BUY"
                    hasil["order"] = order
    elif sinyal == "SELL":
        pos = st["pos"][pair]
        if pos["qty"] * bid < MIN_ORDER:
            hasil["aksi"] = "SELL ditolak: di bawah minimum order"
        else:
            f = fill_jual(book["bids"], pos["qty"])
            if f is None:
                hasil["aksi"] = "SELL gagal: bid kosong"
            else:
                bersih = f["notional"] - f["fee"]
                biaya_pokok = pos["cost"] * f["qty"] / pos["qty"]
                st["cash"] += bersih
                if f["sisa"] > 1e-9:
                    pos["qty"] = f["sisa"]
                    pos["cost"] -= biaya_pokok
                else:
                    del st["pos"][pair]
                order = {"waktu_utc": waktu, "pair": pair, "sisi": "SELL", "qty": f["qty"],
                         "best_bid": bid, "best_ask": ask, "harga_fill": f["avg"],
                         "notional": f["notional"], "fee": f["fee"],
                         "harga_sinyal": harga_sinyal,
                         "selisih_pct": (f["avg"] - harga_sinyal) / harga_sinyal * 100,
                         "level_dipakai": f["level"], "pnl": bersih - biaya_pokok}
                log("orders", order)
                hasil["aksi"] = "SELL"
                hasil["order"] = order
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
        lock = False
        try:
            # kill switch: env var ATAU flag Redis (tercatat di log)
            if os.environ.get("KILL_SWITCH") == "1" or redis("GET", "kill_switch") == "1":
                catatan["kill_switch"] = True
                log("calls", catatan)
                self._balas(200, catatan)
                return

            # cegah dua panggilan berjalan bersamaan
            if redis("SET", "lock", "1", "NX", "EX", "120") is None:
                catatan["status"] = "LOCKED"
                log("calls", catatan)
                self._balas(200, catatan)
                return
            lock = True

            server_sec = int(get_json(f"{BASE}/api/server_time")["server_time"]) // 1000
            raw = redis("GET", "state2")
            st = json.loads(raw) if raw else {"cash": MODAL, "pos": {}, "last": {},
                                              "day": "", "day_eq": MODAL, "lastbid": {}}

            # order book semua pasangan + snapshot
            books = {}
            for pair in PAIRS:
                try:
                    b = ambil_book(pair)
                    if b:
                        books[pair] = b
                        st["lastbid"][pair] = b["bid"]
                        log("snapshots", {"waktu_utc": waktu, "pair": pair, "bid": b["bid"],
                                          "ask": b["ask"], "spread_pct": b["spread"],
                                          "buy": b["raw"]["buy"][:20], "sell": b["raw"]["sell"][:20]})
                except Exception as e:
                    catatan["error"].append({"pair": pair, "pesan": f"depth: {e}"})
                time.sleep(0.4)

            # equity, pergantian hari WIB, daily loss limit
            equity = hitung_equity(st, books)
            hari = hari_wib(server_sec)
            if st["day"] != hari:
                st["day"] = hari
                st["day_eq"] = equity
                log("equity", {"hari_wib": hari, "waktu_utc": waktu, "equity": equity,
                               "cash": st["cash"], "posisi": st["pos"]})
            halted = equity < st["day_eq"] * (1 - DAILY_LOSS_LIMIT)
            catatan.update(equity=equity, cash=st["cash"], posisi=list(st["pos"]),
                           daily_loss_halt=halted)

            for pair in PAIRS:
                try:
                    catatan["hasil"].append(
                        proses_pair(pair, server_sec, st, books, waktu, halted, equity))
                except Exception as e:
                    catatan["error"].append({"pair": pair, "pesan": str(e)})
                time.sleep(0.4)

            redis("SET", "state2", json.dumps(st))
        except Exception as e:
            catatan["error"].append({"pesan": str(e)})
        finally:
            if lock:
                try:
                    redis("DEL", "lock")
                except Exception:
                    pass

        try:
            log("calls", catatan)
        except Exception:
            pass
        self._balas(200, catatan)
