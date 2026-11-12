# UAS Algoritma Trading: Bot Dry Run Indodax

Hafiz Alfarisi, NIM 25110200002, Kelas Trad1
Repo: https://github.com/hafiz12345-svg/uas-bot-trading
Dashboard: https://uas-bot-trading.vercel.app

Bot ini **dry run**: tidak memakai uang asli dan tidak mengirim order ke Indodax.
Semua order dan fill disimulasikan dari order book publik Indodax.

## Catatan waktu (jujur)

Saya mulai mengerjakan terlambat (9 Nov 2026). Dosen mengizinkan forward test
dengan waktu yang tersedia. Bot dibekukan (freeze) pada commit `0f1b628`,
10 Nov 2026 16.11 WIB. Forward test berjalan sejak freeze sampai pengumpulan,
jadi sampelnya pendek (beberapa hari). Tidak ada commit yang ditanggali ulang
dan riwayat git tidak ditulis ulang.

## Bukti freeze

Commit `0f1b628` berisi `signal_strategy.py`, `api/tick.py`, parameter, dan
universe. Setelah commit itu tidak ada perubahan aturan, parameter, atau
universe (lihat "Log perubahan setelah freeze").

## Strategi

Donchian breakout, long-only, timeframe 1 jam.

- **BUY** jika close candle terakhir yang sudah tutup lebih tinggi dari close
  tertinggi 20 candle sebelumnya, dan belum ada posisi di pasangan itu.
- **SELL** jika close candle terakhir yang sudah tutup lebih rendah dari close
  terendah 10 candle sebelumnya, dan ada posisi.
- Fungsi `signal()` ada di `signal_strategy.py` dan dipakai **sama persis** oleh
  bot (`api/tick.py`) dan backtest (`backtest.py`). Tidak ada salinan logika.

Hubungan dengan UTS: strategi breakout dari UTS (data harian saham) dibawa ke
kripto 1 jam. Konsekuensinya dibahas di `refleksi.md`.

## Universe

BTC/IDR, ETH/IDR, XRP/IDR. Ditetapkan sebelum freeze dan tidak diubah.

## Parameter (dibekukan)

| Parameter | Nilai |
|---|---|
| Modal awal | Rp100.000.000 |
| Fee taker | 0,41555% per sisi (BUY dan SELL) |
| Order minimum | Rp25.000 |
| Posisi maksimum bersamaan | 3 |
| Ukuran maksimum per posisi | 30% dari equity |
| Daily loss limit | 3% (batas hari WIB) |
| Spread maksimum | 2% (di atas itu SKIP) |
| Retry API | 3 kali |

## Sumber fee (diperiksa dua sumber)

| Sumber | Fee taker | Diakses |
|---|---|---|
| `/api/pairs` Indodax | 0,41555% (`trade_fee_percent_taker`) | 10 Nov 2026 |
| [Rincian Biaya Transaksi di INDODAX](https://help.indodax.com/hc/id/articles/4416646599705-Rincian-Biaya-Transaksi-di-INDODAX) | IDR Market (PRO): BUY taker 0,20555%, SELL taker 0,41555% | 12 Nov 2026 |

Rincian SELL taker: service fee 0,20% + pajak 0,21% + CFX fee 0,00555% = 0,41555%.

Bot dan backtest memakai **0,41555% untuk BUY dan SELL**, yaitu angka yang
lebih mahal (SELL taker). Dua sumber sama, jadi tidak ada selisih yang harus
dicatat. Fee BUY sebenarnya lebih murah (0,20555%), sehingga biaya BUY di
simulasi sedikit lebih tinggi dari kenyataan (konservatif).

## Eksekusi (realistis)

- Order diisi dengan menelusuri order book (bid/ask) sesuai ukuran order,
  bukan di harga tengah atau harga close.
- Fee taker dan order minimum diterapkan pada setiap fill.
- Equity dinilai pada bid terbaik (harga yang bisa didapat kalau menjual).
- Backtest mengisi order di open candle berikutnya, ditambah biaya per sisi
  yang ditaksir dari snapshot order book **sebelum freeze** (median per pasangan,
  notional Rp30 juta). File snapshot ikut dikumpulkan di repo.

## Risk management (terbukti di log)

- Batas jumlah posisi dan ukuran maksimum per posisi.
- Daily loss limit dengan batas hari WIB.
- Kill switch tanpa deploy ulang: variabel `KILL_SWITCH=1` di Vercel, atau key
  Redis `kill_switch` bernilai `1`. Pemakaiannya tercatat di log.
- Retry terbatas (3 kali) untuk error API, timeout, dan respons kosong.
- Idempotency: setiap candle hanya diproses sekali per pasangan (state di
  Redis), ditambah kunci `lock` agar dua panggilan bersamaan tidak membeli dua
  kali. Terbukti di log dengan status `SUDAH_DIPROSES`.
- Validasi data: candle terakhir lebih tua dari 2x timeframe, candle hilang di
  jendela indikator, harga atau volume nol, order book kosong, spread lebih
  dari 2%. Alasan setiap SKIP dicatat di log.

## Arsitektur

GitHub Actions (menit ke-7, ke-27, dan ke-47 setiap jam,
`.github/workflows/tick.yml`) memanggil endpoint `/api/tick` di Vercel dengan
header Authorization. State dan log disimpan di Upstash Redis dengan key:
`calls`, `orders`, `equity`, `snapshots`, `state2`. Secret (`CRON_SECRET`,
kredensial Redis) hanya ada di environment variable Vercel dan GitHub Secrets.
Tidak ada file `.env` atau secret di repositori. Contoh variabel ada di
`.env.example`.

## Cara menjalankan ulang

1. `hitung_ulang.py`: menarik log mentah dari Redis, menulis `hasil_forward.json`
   dan folder `logs/` (calls, orders, equity harian, error, snapshot, log sinyal).
   Butuh `KV_REST_API_URL` dan `KV_REST_API_TOKEN` (dari env atau diketik saat
   diminta).
2. `python backtest.py --unduh`: mengunduh candle 3 tahun dan menjalankan backtest
   penuh. Hasil: `hasil_backtest.json`, `backtest_trades.csv`, `backtest_equity.csv`.
3. `python backtest.py --bandingkan logs/log_sinyal.csv --orders logs/orders.json`:
   membandingkan sinyal dan fill bot dengan backtest pada jendela waktu yang
   sama. Hasil: `hasil_kecocokan.json`, `perbandingan_sinyal.csv`.
4. Dashboard: `index.html` membaca tiga file JSON di atas.
   `dashboard_offline.html` adalah versi yang datanya sudah tertanam, bisa
   dibuka tanpa internet.

## Dashboard

Online: https://uas-bot-trading.vercel.app. Isinya: return, CAGR, max drawdown,
profit factor, win rate, rata-rata untung dan rugi, jumlah trade, porsi biaya
(fee + spread + slippage) terhadap laba kotor, buy and hold BTC/IDR, selisih
backtest vs forward pada jendela yang sama, dan panel operasional (uptime,
error API, pemakaian kill switch). Semua angka dibaca dari file JSON, tidak ada
angka yang ditulis tangan di HTML.

## Refleksi

Lihat `refleksi.md`.

## Log perubahan setelah freeze

Freeze: commit `0f1b628`, 10 Nov 2026 16.11 WIB. Setelah itu **tidak ada
perubahan pada aturan, parameter, atau universe**. `signal_strategy.py` dan
`api/tick.py` tidak diubah. Yang berubah hanya hal berikut (tanggal tepatnya
bisa dicek di riwayat commit):

| Perubahan | Alasan | Mengubah aturan? |
|---|---|---|
| Menambah `index.html` (dashboard), `hasil_forward.json`, `hasil_backtest.json`, `hasil_kecocokan.json` | Dashboard dan hasil perhitungan, sesuai syarat ujian | Tidak |
| Menambah `hitung_ulang.py` | Menghitung ulang metrik forward dari log mentah di Redis | Tidak |
| Menambah `backtest.py` | Kode backtest versi awal tidak tersimpan, jadi ditulis ulang. Hasilnya dicek dengan angka lama (-97,37% vs -96,72%, selisih kecil). Versi ini yang resmi. Signalnya memakai `signal()` yang sama dengan bot | Tidak |
| `.github/workflows/tick.yml`: menambah jadwal cadangan di menit ke-27 dan ke-47 (selain menit ke-7), 12 Nov 2026 | GitHub Actions sering terlambat 45-55 menit dan kadang melewatkan jam, sehingga uptime turun. Jadwal tambahan memperbesar peluang tiap jam terproses minimal satu kali | Tidak. Ini perubahan infrastruktur penjadwal. Bot tetap memproses tiap candle sekali (idempotency), jadi sinyal dan order tidak berubah |
| Fee dicek ulang ke halaman resmi Indodax (lihat Sumber fee) | Syarat ujian: cek dua sumber | Tidak, angkanya sama |

### Uji kill switch (12 Nov 2026)

Kill switch diuji satu kali pada 12 Nov 2026 sekitar 20.17 WIB, setelah candle
jam 20.00 selesai diproses supaya tidak ada candle yang terlewat:

1. Key Redis `kill_switch` diisi `1`.
2. Bot dipanggil manual lewat GitHub Actions (tick #60, `workflow_dispatch`).
3. Balasan bot: `{"waktu_utc": "2026-11-12T13:17:55...", "hasil": [], "error": [], "kill_switch": true}`
   dengan HTTP 200. Tidak ada pair yang diproses dan tidak ada order.
4. Key `kill_switch` dihapus (`DEL`), dan bot kembali normal.

Panggilan ini tercatat di log dan muncul pada kotak "Kill switch dipakai" di
dashboard. Panggilan ini bukan perubahan aturan atau kode.

Daily loss limit belum pernah terpicu selama forward test (belum ada hari
dengan rugi 3%), jadi belum ada bukti di log untuk fitur itu.
