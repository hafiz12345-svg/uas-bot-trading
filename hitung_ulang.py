"""hitung_ulang.py
Menghasilkan ulang SEMUA angka forward test dari log mentah di Upstash Redis
(daftar: calls, orders, equity, snapshots), lalu menulis:
  - hasil_forward.json     : angka yang dibaca dashboard
  - logs/                  : log mentah (CSV/JSON) untuk dikumpulkan
Tidak ada angka yang ditulis manual. Kredensial dibaca dari environment variable
KV_REST_API_URL dan KV_REST_API_TOKEN (kalau tidak ada, ditanya lewat getpass).
"""
import os, json, csv, getpass, statistics, shutil, requests
from datetime import datetime, timezone

URL = (os.environ.get("KV_REST_API_URL") or getpass.getpass("KV_REST_API_URL: ")).strip()
TOK = (os.environ.get("KV_REST_API_TOKEN") or getpass.getpass("KV_REST_API_TOKEN: ")).strip()
FREEZE = datetime(2026, 11, 10, 9, 11, tzinfo=timezone.utc)   # commit freeze 0f1b628, 16.11 WIB
MODAL = 100_000_000
FOLDER_LOG = "logs"


def redis(*cmd):
    r = requests.post(URL, headers={"Authorization": f"Bearer {TOK}"}, json=list(cmd), timeout=30)
    r.raise_for_status()
    return r.json()["result"]


def baca(key):
    return [json.loads(s) for s in (redis("LRANGE", key, 0, -1) or [])]


def waktu(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def jam(d):
    return d.replace(minute=0, second=0, microsecond=0)


def tambah(d, k):
    d[k] = d.get(k, 0) + 1


# ---------- ambil log mentah ----------
calls_semua, orders_semua = baca("calls"), baca("orders")
equity_harian_semua, snaps_semua = baca("equity"), baca("snapshots")

sesudah = lambda xs: sorted((x for x in xs if waktu(x["waktu_utc"]) >= FREEZE), key=lambda x: x["waktu_utc"])
calls, orders = sesudah(calls_semua), sesudah(orders_semua)
equity_harian, snaps = sesudah(equity_harian_semua), sesudah(snaps_semua)
sekarang = datetime.now(timezone.utc)

# ---------- uptime & keterlambatan ----------
# Panggilan di jam H memproses candle yang tutup pada jam H. Satu candle "terlaksana" bila ada
# minimal satu panggilan sebelum candle berikutnya tutup (yaitu di dalam jam H).
harapan = int((jam(sekarang) - jam(FREEZE)).total_seconds() // 3600)
jam_terpanggil = {jam(waktu(c["waktu_utc"])) for c in calls if jam(waktu(c["waktu_utc"])) < jam(sekarang)}
telat = [(waktu(c["waktu_utc"]).minute + waktu(c["waktu_utc"]).second / 60 - 7) % 60 for c in calls]

# ---------- equity & drawdown (dari tiap panggilan) ----------
kurva = [(c["waktu_utc"], c["equity"]) for c in calls if "equity" in c]
puncak, mdd = MODAL, 0.0
for _, e in kurva:
    puncak = max(puncak, e)
    mdd = min(mdd, e / puncak - 1)
akhir = kurva[-1][1] if kurva else MODAL

# ---------- order & trade ----------
jual = [o for o in orders if o["sisi"] == "SELL"]
untung = [o["pnl"] for o in jual if o["pnl"] > 0]
rugi = [o["pnl"] for o in jual if o["pnl"] <= 0]

# ---------- log per panggilan: error, skip, sinyal, kill switch, idempotency ----------
errors, skip, ditolak, sinyal_count, log_sinyal = [], {}, {}, {}, []
kill_switch = locked = sudah_diproses = 0
for c in calls:
    for e in c.get("error", []):
        errors.append({"waktu_utc": c["waktu_utc"], **e})
    if c.get("kill_switch"):
        kill_switch += 1
    if c.get("status") == "LOCKED":
        locked += 1
    for h in c.get("hasil", []):
        st = h.get("status")
        if st == "SKIP":
            tambah(skip, h.get("alasan", "?"))
        elif st == "SUDAH_DIPROSES":
            sudah_diproses += 1
        elif st == "OK":
            tambah(sinyal_count, f'{h["pair"]}:{h["sinyal"]}')
            log_sinyal.append({"waktu_utc": c["waktu_utc"], "pair": h["pair"], "candle": h["candle"],
                               "close": h["close"], "sinyal": h["sinyal"], "aksi": h.get("aksi", "")})
            if "ditolak" in h.get("aksi", "") or "gagal" in h.get("aksi", ""):
                tambah(ditolak, h["aksi"])
halt_hari = sum(1 for c in calls if c.get("daily_loss_halt"))

# ---------- spread dari snapshot ----------
spr = {}
for s in snaps:
    spr.setdefault(s["pair"], []).append(s["spread_pct"])

ada_posisi = [c for c in calls if "posisi" in c]   # panggilan kill switch/LOCKED tidak memuat posisi
posisi_terbuka = ada_posisi[-1]["posisi"] if ada_posisi else []

hasil = {
    "freeze_utc": FREEZE.isoformat(),
    "dihitung_utc": sekarang.isoformat(),
    "panggilan": len(calls),
    "jam_selesai_terpanggil": len(jam_terpanggil),
    "jam_selesai_seharusnya": harapan,
    "uptime_pct": round(100 * len(jam_terpanggil) / harapan, 1) if harapan else None,
    "keterlambatan_menit_median": round(statistics.median(telat), 1) if telat else None,
    "keterlambatan_menit_maks": round(max(telat), 1) if telat else None,
    "equity_akhir": round(akhir, 2),
    "return_pct": round((akhir / MODAL - 1) * 100, 4),
    "max_drawdown_pct": round(mdd * 100, 4),
    "jumlah_order": len(orders),
    "trade_tertutup": len(jual),
    "win_ratio_pct": round(100 * len(untung) / len(jual), 1) if jual else None,
    "rata2_untung": round(statistics.mean(untung), 2) if untung else None,
    "rata2_rugi": round(statistics.mean(rugi), 2) if rugi else None,
    "total_fee": round(sum(o["fee"] for o in orders), 2),
    "selisih_fill_vs_sinyal_rata2_pct": round(statistics.mean(o["selisih_pct"] for o in orders), 4) if orders else None,
    "error_total": len(errors),
    "alasan_skip": skip,
    "alasan_ditolak": ditolak,
    "jumlah_sinyal": sinyal_count,
    "kill_switch_dipakai": kill_switch,
    "panggilan_locked": locked,
    "candle_sudah_diproses": sudah_diproses,
    "panggilan_daily_loss_halt": halt_hari,
    "posisi_terbuka": posisi_terbuka,
    "median_spread_pct": {p: round(statistics.median(v), 4) for p, v in spr.items()},
    "jumlah_snapshot": len(snaps),
    "equity_harian": [{"hari_wib": e["hari_wib"], "waktu_utc": e["waktu_utc"], "equity": round(e["equity"], 2)}
                      for e in equity_harian],
    "kurva_equity": [[t, round(e, 2)] for t, e in kurva],
    "orders": orders,
}
with open("hasil_forward.json", "w") as f:
    json.dump(hasil, f, ensure_ascii=False, indent=1)

# ---------- tulis log mentah ----------
os.makedirs(FOLDER_LOG, exist_ok=True)
with open(f"{FOLDER_LOG}/calls.json", "w") as f:
    json.dump(calls_semua, f, ensure_ascii=False, indent=1)
with open(f"{FOLDER_LOG}/orders.json", "w") as f:
    json.dump(orders_semua, f, ensure_ascii=False, indent=1)
with open(f"{FOLDER_LOG}/equity_harian.json", "w") as f:
    json.dump(equity_harian_semua, f, ensure_ascii=False, indent=1)
with open(f"{FOLDER_LOG}/errors.json", "w") as f:
    json.dump(errors, f, ensure_ascii=False, indent=1)
with open(f"{FOLDER_LOG}/snapshots.jsonl", "w") as f:
    for s in snaps_semua:
        f.write(json.dumps(s, ensure_ascii=False) + "\n")
with open(f"{FOLDER_LOG}/log_sinyal.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["waktu_utc", "pair", "candle", "close", "sinyal", "aksi"])
    w.writeheader()
    w.writerows(log_sinyal)

ringkas = {k: v for k, v in hasil.items() if k not in ("kurva_equity", "orders", "equity_harian")}
print(json.dumps(ringkas, ensure_ascii=False, indent=1))
print(f"\nLog mentah: {len(calls_semua)} panggilan, {len(orders_semua)} order, "
      f"{len(equity_harian_semua)} equity harian, {len(snaps_semua)} snapshot, {len(errors)} error.")

try:
    from google.colab import files
    shutil.make_archive("logs", "zip", FOLDER_LOG)
    files.download("hasil_forward.json")
    files.download("logs.zip")
except ImportError:
    pass
