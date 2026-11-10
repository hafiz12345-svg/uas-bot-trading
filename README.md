# UAS Algoritma Trading: Bot Dry Run Indodax

Nama: Hafiz Alfarisi | NIM: 25110200002 | Kelas: Trad1
Repositori: https://github.com/hafiz12345-svg/uas-bot-trading
Bot (endpoint terlindungi): https://uas-bot-trading.vercel.app/api/tick

## Catatan waktu (jujur)
Saya baru mulai mengerjakan UAS ini pada Senin 9 November 2026 karna saya punya kendala di laptopnya rusak dan sudah mencoba berusaha buat minjem, setelah freeze date di soal (Rabu 4 November 2026, 12.00 WIB). Saya sudah menghubungi dosen lewat WhatsApp
- Bot ter-deploy di Vercel dan dipanggil terjadwal sejak Selasa 10 November 2026 sekitar pukul 15.20 WIB (versi 1: hanya mencatat sinyal).
- Versi 2 (eksekusi simulasi dan risk management) aktif sekitar pukul 15.45 WIB hari yang sama.
- Commit freeze adalah commit dengan pesan "FREEZE: aturan, parameter, universe". Hash dan jamnya dicatat di bagian "Bukti freeze".
- Forward test berjalan dari commit freeze sampai pengumpulan, jadi kurang dari 10 hari (sekitar 4 hari). Tidak ada tanggal commit yang diubah dan tidak ada riwayat yang ditulis ulang.

## Bukti freeze
- Hash commit freeze: (diisi setelah commit)
- Waktu commit freeze: (diisi setelah commit)

## Strategi (breakout Donchian, long-only)
- Timeframe 1 jam. Sinyal hanya dihitung dari candle yang sudah tertutup.
- BUY: close candle terakhir lebih tinggi dari close tertinggi 20 candle sebelumnya, dan belum memegang posisi pada pasangan itu.
- SELL: close candle terakhir lebih rendah dari close terendah 10 candle sebelumnya, dan sedang memegang posisi pada pasangan itu.
- Tanpa short, margin, atau leverage.
- Fungsi sinyal ada di `signal_strategy.py` dan dipakai bersama oleh backtest dan bot.

### Hubungan dengan strategi UTS
Strategi UTS saya adalah Donchian Breakout dengan filter tren SMA, long-only, pada saham Kompas100 (98 saham, data harian). Aturannya: masuk bila close menembus high tertinggi 55 hari dan close di atas SMA 150, keluar bila close menembus low terendah 30 hari. Parameter itu dipilih dari data in-sample UTS (CAGR backtest 32%, max drawdown 47%, 283 trade).
Untuk UAS, inti breakout Donchian dan sifat long-only dipertahankan. Perubahan untuk kripto:
- Timeframe harian diganti 1 jam, karena kripto diperdagangkan 24 jam dan forward test hanya beberapa hari.
- Jendela masuk 20 candle dan keluar 10 candle (UTS: 55 dan 30). Jendela dipendekkan agar ada sinyal dalam periode forward test yang singkat. Angka ini dipilih sebelum backtest kripto dijalankan, bukan dari optimasi.
- Filter SMA 150 dihapus demi kesederhanaan dan agar fungsi sinyal bisa dipakai identik oleh backtest dan bot. Ini penyederhanaan yang saya sadari dan bisa melemahkan strategi di pasar sideways.
- Biaya, spread, dan eksekusi memakai order book Indodax, bukan fraksi harga BEI.

## Universe
BTC/IDR, ETH/IDR, XRP/IDR.

Kriteria pemilihan: pasangan IDR yang likuid, dinilai dari spread bid-ask dan nilai 10 level bid di order book. Pengukuran 10 November 2026: XRP/IDR spread 0,005% dan nilai 10 level bid Rp758.903.051; SOL/IDR spread 0,125% dan Rp763.292.720. XRP dipilih karena spread lebih rapat.

Survivorship bias: ketiga pasangan punya data historis lengkap 3 tahun (26.281 bar per jam, 11 November 2023 sampai 10 November 2026).
Keterbatasan: likuiditas diukur pada 10 November 2026, bukan pada awal periode backtest, karena saya belum punya snapshot order book historis. Ini dicatat sebagai keterbatasan.

## Parameter (dibekukan)
- Modal virtual Rp100.000.000
- Maksimum 3 posisi terbuka, maksimum 30% equity per posisi
- Fee taker 0,41555% untuk beli dan jual (lihat bagian fee)
- Minimum order Rp25.000
- Daily loss limit 3% dari equity awal hari. Batas hari memakai WIB (00.00 WIB). Bila terlampaui, bot berhenti membuka posisi baru sampai hari berikutnya.
- Tidak membuka posisi bila spread bid-ask lebih dari 2%

## Fee dan minimum order
- API publik: https://indodax.com/api/pairs, `trade_fee_percent_taker` = 0,2%. Diakses 10 November 2026.
- Aplikasi Indodax, menu Trading Fee, IDR Market (PRO), diakses 10 November 2026 pukul 15.49 WIB:
  - Taker beli 0,20555% (service fee 0,2% + pajak 0% + bourse fee 0,00555%)
  - Taker jual 0,41555% (service fee 0,2% + pajak 0,21% + bourse fee 0,00555%)
- Halaman rincian biaya resmi di help.indodax.com: belum dibuka saat commit ini dibuat; angka di atas berasal dari aplikasi. Alamat halaman akan ditambahkan lewat commit terpisah dan dicatat di log perubahan.
- Yang dipakai: 0,41555% (angka yang lebih mahal) untuk beli dan jual.
- Minimum order: `trade_min_base_currency` di /api/pairs adalah Rp10.000, sedangkan rincian resmi menyebut order langsung di Pro minimal Rp25.000. Yang dipakai: Rp25.000 (yang lebih ketat).

## Eksekusi dry run
- Beli di ask dan jual di bid dari order book live. Order yang lebih besar dari level terbaik menghabiskan level berikutnya dan memakai harga rata-rata tertimbang.
- Tidak ada fill di harga tengah (mid) atau close.
- Posisi terbuka dinilai pada best bid (nilai jika dijual saat itu).
- Setiap order dicatat: waktu, pasangan, sisi, kuantitas, best bid dan best ask, harga fill rata-rata, fee, selisih terhadap harga sinyal.

## Risk management (ada di kode `api/tick.py`)
- Batas jumlah posisi dan ukuran maksimum per posisi.
- Daily loss limit dengan batas hari WIB.
- Kill switch tanpa deploy ulang: variabel `KILL_SWITCH=1` di Vercel, atau key Redis `kill_switch` bernilai `1`. Pemakaiannya tercatat di log.
- Retry terbatas (3 kali) untuk error API, timeout, dan respons kosong.
- Idempotency: setiap candle hanya diproses sekali per pasangan (state di Redis), ditambah kunci `lock` agar dua panggilan bersamaan tidak membeli dua kali.
- Validasi data: candle terakhir lebih tua dari 2x timeframe, candle hilang di jendela indikator, harga atau volume nol, order book kosong, spread lebih dari 2%. Alasan setiap SKIP dicatat di log.

## Arsitektur
GitHub Actions (menit ke-7 setiap jam, `.github/workflows/tick.yml`) memanggil endpoint di Vercel dengan header Authorization. State dan log disimpan di Upstash Redis dengan key: `calls`, `orders`, `equity`, `snapshots`, `state2`.
Secret (`CRON_SECRET`, kredensial Redis) hanya ada di environment variable Vercel dan GitHub Secrets. Tidak ada file `.env` atau secret di repositori.

## Log perubahan setelah freeze
(belum ada. Setiap perbaikan bug yang tidak mengubah aturan akan dicatat di sini beserta tanggal dan alasan.)
