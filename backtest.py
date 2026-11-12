"""backtest.py
Backtest strategi Donchian breakout (long-only, 1 jam) dengan fungsi sinyal YANG SAMA dengan bot
(signal_strategy.py) dan aturan eksekusi yang sama dengan api/tick.py.

Pemakaian (Colab atau terminal):
  python backtest.py --unduh              # tarik candle 3 tahun terakhir dari Indodax, lalu backtest penuh
  python backtest.py                      # backtest penuh dari file *_1h.csv yang sudah ada
  python backtest.py --bandingkan logs/log_sinyal.csv --orders logs/orders.json
                                          # backtest ulang pada jendela forward test + perbandingan sinyal & fill
Hasil: backtest_trades.csv, backtest_equity.csv, hasil_backtest.json (penuh);
       hasil_kecocokan.json, perbandingan_sinyal.csv (mode --bandingkan).
"""
import os, sys, csv, json, math, time, argparse, statistics, urllib.request
from datetime import datetime, timezone

try:
    from signal_strategy import signal, N_MASUK
except ImportError:  # di Colab: ambil file yang sama dari repo
    kode = urllib.request.urlopen(
        "https://raw.githubusercontent.com/hafiz12345-svg/uas-bot-trading/main/signal_strategy.py").read().decode()
    _ns = {}
    exec(kode, _ns)
    signal, N_MASUK = _ns["signal"], _ns["N_MASUK"]

BASE = "https://indodax.com"
PAIRS = ["BTCIDR", "ETHIDR", "XRPIDR"]
TF = 3600
# ---- parameter yang sama dengan bot (api/tick.py) ----
MODAL = 100_000_000
FEE_TAKER = 0.0041555
MIN_ORDER = 25_000
MAX_POSITIONS = 3
MAX_POS_FRAC = 0.30
DAILY_LOSS_LIMIT = 0.03
NOTIONAL_BIAYA = 30_000_000          # ukuran order untuk menaksir spread+slippage dari order book
FREEZE_ISO = "2026-11-10T09:11:00+00:00"


# ---------------- data candle ----------------
def unduh_candle(pair, tahun=3):
    """Tarik candle 1 jam mundur ke belakang (sekitar 650 bar per tarikan)."""
    import requests
    awal = int(time.time()) - tahun * 365 * 24 * 3600
    semua, ke = {}, int(time.time())
    while True:
        data = requests.get(f"{BASE}/tradingview/history_v2",
                            params={"symbol": pair, "tf": "60", "from": awal, "to": ke}, timeout=15).json()
        if not data:
            break
        for b in data:
            semua[b["Time"]] = b
        paling_awal = min(b["Time"] for b in data)
        if paling_awal <= awal or paling_awal >= ke:
            break
        ke = paling_awal
        time.sleep(0.4)
    urut = sorted(semua.values(), key=lambda b: b["Time"])
    with open(f"{pair.lower()}_1h.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["Time", "Open", "High", "Low", "Close", "Volume"])
        w.writeheader()
        w.writerows(urut)
    print(f"{pair}: {len(urut)} bar")


def muat_candle(pair):
    with open(f"{pair.lower()}_1h.csv") as f:
        rows = [{"Time": int(r["Time"]), "Open": float(r["Open"]), "Close": float(r["Close"])}
                for r in csv.DictReader(f)]
    rows.sort(key=lambda r: r["Time"])
    return rows[:-1]          # buang bar terakhir (belum tentu sudah tertutup)


# ---------------- biaya dari snapshot order book ----------------
def taksir_biaya(snap, notional=NOTIONAL_BIAYA):
    """(biaya_beli, biaya_jual) relatif terhadap mid, dengan menelusuri level order book."""
    bids = sorted([(float(p), float(v)) for p, v in snap["buy"]], reverse=True)
    asks = sorted([(float(p), float(v)) for p, v in snap["sell"]])
    mid = (bids[0][0] + asks[0][0]) / 2
    sisa, qty, spent = notional, 0.0, 0.0
    for p, v in asks:
        ambil = min(v, sisa / p)
        qty += ambil; spent += ambil * p; sisa -= ambil * p
        if sisa <= 1e-9: break
    beli = spent / qty / mid - 1
    sisa_q, got, terjual = notional / mid, 0.0, 0.0
    for p, v in bids:
        ambil = min(v, sisa_q)
        got += ambil * p; terjual += ambil; sisa_q -= ambil
        if sisa_q <= 1e-12: break
    jual = 1 - got / terjual / mid
    return beli, jual


def biaya_per_pair(file_snapshot, file_log_bot=None, sebelum=FREEZE_ISO):
    """Median biaya beli/jual per pair dari snapshot SEBELUM freeze."""
    snaps = []
    for fn in file_snapshot:
        if os.path.exists(fn):
            snaps += [json.loads(l) for l in open(fn) if l.strip()]
    if file_log_bot and os.path.exists(file_log_bot):
        snaps += [json.loads(l) for l in open(file_log_bot) if l.strip()]
    hasil, jumlah = {}, {}
    for s in snaps:
        if s["waktu_utc"] >= sebelum:
            continue
        p = s["pair"].upper()
        try:
            hasil.setdefault(p, []).append(taksir_biaya(s))
        except Exception:
            continue
    biaya = {}
    for p in PAIRS:
        if p not in hasil:
            raise SystemExit(f"Tidak ada snapshot sebelum freeze untuk {p}. Tambahkan file snapshot.")
        biaya[p] = (statistics.median(b for b, _ in hasil[p]), statistics.median(j for _, j in hasil[p]))
        jumlah[p] = len(hasil[p])
    return biaya, jumlah


# ---------------- simulasi portofolio ----------------
def floor8(x): return math.floor(x * 1e8) / 1e8


def hari_wib(ts): return datetime.fromtimestamp(ts + 7 * 3600, timezone.utc).strftime("%Y-%m-%d")


def simulasi(candles, biaya, mulai=None, akhir=None, modal=MODAL):
    """Sinyal dievaluasi pada candle yang sudah tertutup; order terisi di OPEN candle berikutnya
    (+biaya beli / -biaya jual). Aturan sama dengan bot: maks 3 posisi, 30% equity per posisi,
    daily loss limit 3% (hari WIB), fee taker tiap sisi, minimum order."""
    idx = {p: {c["Time"]: i for i, c in enumerate(cs)} for p, cs in candles.items()}
    closes = {p: [c["Close"] for c in cs] for p, cs in candles.items()}
    waktu_semua = sorted({c["Time"] for cs in candles.values() for c in cs})
    cash, pos, last_close = modal, {}, {}
    day, day_eq = None, modal
    trades, equity, log_sinyal = [], [], []
    for t in waktu_semua:
        for p in PAIRS:
            if t in idx[p]:
                last_close[p] = closes[p][idx[p][t]]
        eq = cash + sum(q["qty"] * last_close[p] * (1 - biaya[p][1]) for p, q in pos.items())
        dalam = (mulai is None or t >= mulai) and (akhir is None or t <= akhir)
        if not dalam:
            continue
        equity.append((t + TF, eq))
        hari = hari_wib(t + TF)
        if hari != day:
            day, day_eq = hari, eq
        halted = eq < day_eq * (1 - DAILY_LOSS_LIMIT)
        for p in PAIRS:
            if t not in idx[p]:
                continue
            i = idx[p][t]
            punya = p in pos
            s = signal(closes[p][:i + 1], punya)
            log_sinyal.append({"pair": p, "candle": t, "sinyal": s})
            if s == "HOLD" or i + 1 >= len(candles[p]):
                continue
            nxt = candles[p][i + 1]
            if s == "BUY" and not punya:
                if halted or len(pos) >= MAX_POSITIONS:
                    continue
                harga = nxt["Open"] * (1 + biaya[p][0])
                budget = min(MAX_POS_FRAC * eq, cash)
                qty = floor8(budget / (1 + FEE_TAKER) / harga)
                notional = qty * harga
                if notional < MIN_ORDER:
                    continue
                fee = notional * FEE_TAKER
                cash -= notional + fee
                pos[p] = {"qty": qty, "cost": notional + fee, "t": nxt["Time"], "harga": harga,
                          "open": nxt["Open"], "fee_in": fee}
            elif s == "SELL" and punya:
                q = pos.pop(p)
                harga = nxt["Open"] * (1 - biaya[p][1])
                bruto = q["qty"] * harga
                fee = bruto * FEE_TAKER
                cash += bruto - fee
                pnl = bruto - fee - q["cost"]
                trades.append({
                    "pair": p, "masuk": q["t"], "keluar": nxt["Time"],
                    "harga_masuk": q["harga"], "harga_keluar": harga, "pnl": pnl,
                    "pct": pnl / q["cost"], "jam": (nxt["Time"] - q["t"]) / 3600,
                    "fee": q["fee_in"] + fee,
                    "spread_slippage": q["qty"] * q["open"] * biaya[p][0] + q["qty"] * nxt["Open"] * biaya[p][1],
                    "laba_kotor": q["qty"] * (nxt["Open"] - q["open"])})
    return trades, equity, log_sinyal, pos


# ---------------- metrik ----------------
def metrik(trades, equity, candles_btc, modal=MODAL):
    nilai = [e for _, e in equity]
    akhir = nilai[-1]
    puncak, mdd = nilai[0], 0.0
    for v in nilai:
        puncak = max(puncak, v); mdd = min(mdd, v / puncak - 1)
    tahun = (equity[-1][0] - equity[0][0]) / (365.25 * 86400)
    untung = [t["pnl"] for t in trades if t["pnl"] > 0]
    rugi = [t["pnl"] for t in trades if t["pnl"] <= 0]
    fee = sum(t["fee"] for t in trades)
    ss = sum(t["spread_slippage"] for t in trades)
    kotor = sum(t["laba_kotor"] for t in trades)
    hasil = {
        "periode": f"{datetime.fromtimestamp(equity[0][0], timezone.utc):%d-%m-%Y} s/d "
                   f"{datetime.fromtimestamp(equity[-1][0], timezone.utc):%d-%m-%Y} ({tahun:.1f} tahun)".replace(".", ","),
        "return_pct": round((akhir / modal - 1) * 100, 2),
        "cagr_pct": round(((akhir / modal) ** (1 / tahun) - 1) * 100, 2) if tahun >= 1 and akhir > 0 else None,
        "max_drawdown_pct": round(mdd * 100, 2),
        "jumlah_trade": len(trades),
        "win_ratio_pct": round(100 * len(untung) / len(trades), 2) if trades else None,
        "profit_factor": round(sum(untung) / -sum(rugi), 2) if rugi and sum(rugi) < 0 else None,
        "rata2_untung": round(statistics.mean(untung), 2) if untung else None,
        "rata2_rugi": round(statistics.mean(rugi), 2) if rugi else None,
        "total_fee": round(fee, 2), "total_spread_slippage": round(ss, 2),
        "laba_kotor_sebelum_biaya": round(kotor, 2),
        "porsi_biaya_pct": round((fee + ss) / kotor * 100, 2) if kotor > 0 else None,
    }
    if candles_btc:
        hasil["buy_hold_btc_pct"] = round((candles_btc[-1]["Close"] / candles_btc[0]["Close"] - 1) * 100, 2)
    return hasil


def kurva(equity, maks=700):
    langkah = max(1, len(equity) // maks)
    idx = list(range(0, len(equity), langkah))
    if idx[-1] != len(equity) - 1: idx.append(len(equity) - 1)
    return [[datetime.fromtimestamp(equity[i][0], timezone.utc).isoformat(), round(equity[i][1], 2)] for i in idx]


# ---------------- perbandingan dengan bot ----------------
def bandingkan(candles, biaya, file_sinyal, file_orders):
    bot = list(csv.DictReader(open(file_sinyal)))
    bot_s = {(r["pair"], int(r["candle"])): r["sinyal"] for r in bot}
    t0, t1 = min(k[1] for k in bot_s), max(k[1] for k in bot_s)
    trades, equity, log, pos = simulasi(candles, biaya, mulai=t0, akhir=t1)
    bt_s = {(r["pair"], r["candle"]): r["sinyal"] for r in log}
    cocok, baris, selisih = 0, [], []
    for k in sorted(bot_s, key=lambda k: (k[1], k[0])):
        b = bt_s.get(k, "(tidak ada candle)")
        ok = b == bot_s[k]
        cocok += ok
        baris.append({"pair": k[0], "candle": k[1], "sinyal_bot": bot_s[k], "sinyal_backtest": b, "sama": ok})
        if not ok: selisih.append(baris[-1])
    tidak_diproses = sorted({(p, c) for (p, c) in bt_s if (p, c) not in bot_s}, key=lambda k: (k[1], k[0]))
    with open("perbandingan_sinyal.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["pair", "candle", "sinyal_bot", "sinyal_backtest", "sama"])
        w.writeheader(); w.writerows(baris)
    # selisih harga fill per order bot vs backtest
    fill = []
    if file_orders and os.path.exists(file_orders):
        for o in json.load(open(file_orders)):
            if o["waktu_utc"] < FREEZE_ISO:
                continue
            p = o["pair"]
            cs = candles[p]
            # candle sinyal = candle terakhir yang tutup sebelum order; fill backtest = open candle berikutnya
            waktu = datetime.fromisoformat(o["waktu_utc"]).timestamp()
            sig = max((c["Time"] for c in cs if c["Time"] + TF <= waktu), default=None)
            nxt = next((c for c in cs if sig is not None and c["Time"] == sig + TF), None)
            if not nxt:
                continue
            mid_bot = (o["best_bid"] + o["best_ask"]) / 2
            sisi = o["sisi"]
            bt_fill = nxt["Open"] * (1 + biaya[p][0]) if sisi == "BUY" else nxt["Open"] * (1 - biaya[p][1])
            bt_biaya = biaya[p][0] if sisi == "BUY" else biaya[p][1]
            bot_biaya = (o["harga_fill"] / mid_bot - 1) if sisi == "BUY" else (1 - o["harga_fill"] / mid_bot)
            fill.append({"pair": p, "sisi": sisi, "waktu_bot_utc": o["waktu_utc"], "harga_fill_bot": o["harga_fill"],
                         "harga_fill_backtest": bt_fill, "open_candle_berikutnya": nxt["Open"],
                         "selisih_total_pct": round((o["harga_fill"] / bt_fill - 1) * 100, 4),
                         "komponen_keterlambatan_jadwal_pct": round((mid_bot / nxt["Open"] - 1) * 100, 4),
                         "komponen_spread_slippage_bot_pct": round(bot_biaya * 100, 4),
                         "komponen_spread_slippage_backtest_pct": round(bt_biaya * 100, 4)})
    hasil = {"jendela_candle_awal": t0, "jendela_candle_akhir": t1,
             "candle_dibandingkan": len(baris), "sinyal_sama": cocok,
             "kecocokan_pct": round(100 * cocok / len(baris), 2) if baris else None,
             "sinyal_berbeda": selisih,
             "candle_tidak_diproses_bot": [{"pair": p, "candle": c} for p, c in tidak_diproses],
             "trade_backtest_pada_jendela": len(trades),
             "perbandingan_fill": fill,
             "metrik_backtest_jendela": metrik(trades, equity, None) if len(equity) > 1 else None}
    json.dump(hasil, open("hasil_kecocokan.json", "w"), ensure_ascii=False, indent=1)
    print(f"Kecocokan sinyal: {cocok} dari {len(baris)} ({hasil['kecocokan_pct']}%)")
    print(f"Candle di jendela yang tidak diproses bot: {len(tidak_diproses)} (pair-candle)")
    for f_ in fill:
        print("Fill:", f_["pair"], f_["sisi"], "selisih total", f_["selisih_total_pct"], "% | jadwal",
              f_["komponen_keterlambatan_jadwal_pct"], "% | spread+slip bot", f_["komponen_spread_slippage_bot_pct"],
              "% vs backtest", f_["komponen_spread_slippage_backtest_pct"], "%")
    return hasil


# ---------------- main ----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unduh", action="store_true", help="tarik candle 3 tahun dari Indodax dulu")
    ap.add_argument("--snapshot", nargs="*", default=["snapshots pagi.jsonl", "snapshots siang.jsonl"])
    ap.add_argument("--log-bot-snapshot", default="logs/snapshots.jsonl")
    ap.add_argument("--bandingkan", help="logs/log_sinyal.csv dari hitung_ulang.py")
    ap.add_argument("--orders", default="logs/orders.json")
    a = ap.parse_args()
    if a.unduh:
        for p in PAIRS:
            unduh_candle(p)
    candles = {p: muat_candle(p) for p in PAIRS}
    biaya, jumlah = biaya_per_pair(a.snapshot, a.log_bot_snapshot)
    for p in PAIRS:
        print(f"{p}: biaya beli {biaya[p][0]*100:.4f}% | jual {biaya[p][1]*100:.4f}% (median {jumlah[p]} snapshot sebelum freeze)")
    if a.bandingkan:
        bandingkan(candles, biaya, a.bandingkan, a.orders)
        return
    trades, equity, _, pos = simulasi(candles, biaya)
    m = metrik(trades, equity, candles["BTCIDR"])
    with open("backtest_trades.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(trades[0].keys()))
        w.writeheader(); w.writerows(trades)
    with open("backtest_equity.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["waktu_utc_detik", "equity"]); w.writerows(equity)
    json.dump({"dihitung_utc": datetime.now(timezone.utc).isoformat(), "ringkasan": m,
               "biaya_per_sisi_pct": {p: {"beli": round(biaya[p][0] * 100, 4), "jual": round(biaya[p][1] * 100, 4),
                                          "jumlah_snapshot": jumlah[p]} for p in PAIRS},
               "catatan": "Dihitung otomatis oleh backtest.py. Sinyal memakai signal_strategy.py yang sama dengan bot.",
               "kurva_equity": kurva(equity)},
              open("hasil_backtest.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(m, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
