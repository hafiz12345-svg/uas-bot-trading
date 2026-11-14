# Refleksi: Backtest vs Forward

Hafiz Alfarisi, NIM 25110200002, Kelas Trad1

Angka di bawah diambil dari dashboard per 14 Nov 2026 sekitar pukul 16.15 WIB.
Angka final ada di `hasil_forward.json`, `hasil_backtest.json`, dan
`hasil_kecocokan.json`.

## 1. Apa hasilnya

| | Backtest (15 Nov 2023 - 14 Nov 2026, 3 tahun) | Forward (10 Nov 2026 15.00 - 14 Nov 2026 14.00 WIB) |
|---|---|---|
| Return | -97,40% | -1,67% |
| Max drawdown | -97,40% | -1,68% |
| Jumlah trade | 1.704 | 3 trade tertutup (6 order) |
| Win rate | 21,7% | 0% (3 dari 3 rugi) |
| Profit factor | 0,52 | 0,00 |
| Buy and hold BTC/IDR | +120,15% (periode sama) | -8,74% (jendela yang sama) |

Pada jendela waktu forward yang sama, backtest menghasilkan -1,76% dan bot
menghasilkan -1,67%, selisihnya sekitar 0,09 poin persentase.

Strategi saya **rugi** di backtest maupun di forward. Aturan tidak saya ubah
untuk memperbaiki hasil, karena sudah dibekukan sebelum forward test.

## 2. Kenapa strategi ini rugi

Penyebab utamanya adalah **biaya**, bukan sinyal yang selalu salah.

- Satu putaran beli-lalu-jual kena fee sekitar 0,83% (0,41555% x 2), belum
  termasuk spread dan slippage.
- Breakout Donchian 20/10 pada data 1 jam menghasilkan sangat banyak trade
  (1.704 trade dalam 3 tahun). Win rate hanya sekitar 22% dan profit factor
  0,52.
- Total biaya (fee + spread + slippage) di backtest adalah sekitar **3,56 kali**
  laba kotor sebelum biaya (355,7%). Laba kotor sebelum biaya sebenarnya positif
  (sekitar Rp38 juta), tetapi biaya sekitar Rp135 juta menelannya habis. Ini
  overtrading.
- Hal yang sama terlihat di forward test. Dari 3 trade tertutup, laba kotor
  sebelum biaya adalah sekitar -Rp886 ribu, ditambah fee sekitar Rp741 ribu dan
  spread/slippage sekitar Rp46 ribu. Jadi sekitar setengah kerugian forward
  berasal dari biaya, dan setengahnya dari pergerakan harga yang tidak
  menguntungkan.
- Buy and hold BTC/IDR di periode backtest naik +120,15%, jadi pasarnya
  sendiri tidak buruk. Yang buruk adalah cara bot masuk-keluar terlalu sering.
  Di jendela forward, BTC justru turun 8,74%, dan bot yang long-only rugi lebih
  kecil daripada buy and hold. Tetapi sampel 3 trade terlalu kecil untuk
  menyimpulkan bot lebih baik.

Pelajaran: strategi dari UTS dibuat untuk data harian saham, dengan trade yang
jarang. Saat dibawa ke kripto 1 jam, jumlah trade naik berkali-kali lipat
sementara biaya per trade tetap, sehingga biaya mengalahkan keunggulan sinyal.

## 3. Apakah forward cocok dengan backtest?

**Sinyal: cocok.** Pada jendela forward, sinyal bot sama dengan sinyal backtest
untuk 267 dari 267 candle yang dibandingkan (100%). Karena `signal()` yang
dipakai bot dan backtest adalah fungsi yang sama dari `signal_strategy.py`,
hasil ini memang yang diharapkan. Ini bukti tidak ada perbedaan logika antara
backtest dan bot.

**Eksekusi: ada selisih per trade, tetapi saling menutupi.** Perbedaan
datang dari harga fill, bukan dari sinyal:

- Backtest mengisi order di **open candle berikutnya**. Bot baru berjalan
  beberapa puluh menit setelah candle tutup, karena penjadwal GitHub Actions
  terlambat (median 33,9 menit, paling lama 59,4 menit). Dampaknya terlihat di
  tabel dashboard pada kolom "Dari keterlambatan jadwal", berkisar sekitar
  -0,6% sampai +0,3% per fill, kadang menguntungkan dan kadang merugikan.
- Selisih akibat spread dan slippage bot kecil (di bawah sekitar 0,1% per fill),
  karena bot mengisi order dengan menelusuri order book.
- Karena selisih per trade ada yang positif dan ada yang negatif, hasil totalnya
  hampir sama (-1,67% vs -1,76%).
- Hanya ada 3 trade tertutup. Dengan sampel sekecil itu, kecocokan return tidak
  bisa dibaca sebagai bukti statistik. Hasil bisa saja berbeda jauh dengan
  trade yang lain.

Kesimpulan: **sinyal identik, eksekusi berbeda sedikit karena waktu dan order
book, dan sampel forward terlalu pendek untuk menilai profitabilitas.**

## 4. Hal yang tidak berjalan baik

- **Uptime 92,6%.** Bot terpanggil pada 88 dari 95 jam selesai. Tujuh jam
  terlewat, sehingga ada 21 pasangan-candle yang tidak diproses di jendela
  perbandingan. Penyebabnya penjadwal GitHub Actions yang sering terlambat atau
  melewatkan jam. Saya menambah jadwal cadangan (menit ke-27 dan ke-47) pada
  12 Nov. Perubahan itu tercatat di README sebagai perubahan infrastruktur, bukan
  perubahan aturan. Saya tidak menghapus atau menyunting log yang sudah ada.
- **Mulai terlambat.** Saya baru mengerjakan pada 9 Nov. Dosen mengizinkan
  forward test dengan waktu yang tersedia, jadi forward test saya hanya sekitar
  4 hari. Itu terlalu pendek untuk menyimpulkan apa pun soal performa.
- **Kode backtest awal tidak tersimpan.** Saya menulis ulang `backtest.py` dan
  mencocokkan hasilnya dengan angka lama (sekitar -97,4% vs -96,7%). Selisihnya
  kecil dan versi baru yang saya pakai sebagai versi resmi.
- **Estimasi biaya backtest.** Biaya per sisi backtest ditaksir dari snapshot
  order book sebelum freeze (BTC dan ETH 5 snapshot, XRP hanya 3). Median spread
  XRP di forward ternyata 0,0824%, lebih lebar dari BTC (0,0235%), dan ETH di
  forward (0,0583%) juga lebih lebar dari taksiran awal. Jadi taksiran biaya di
  backtest kurang kuat, terutama untuk XRP.
- **Fitur risiko yang belum teruji penuh.** Daily loss limit tidak pernah terpicu
  karena tidak ada hari dengan kerugian 3%. Kill switch hanya diuji satu kali
  secara manual (lihat README).

## 5. Yang akan saya ubah kalau punya waktu lagi

1. Memperlambat strategi (timeframe 4 jam atau harian, atau breakout yang lebih
   panjang) supaya jumlah trade turun dan biaya tidak mendominasi.
2. Menambah filter tren atau filter volatilitas supaya tidak masuk pada
   breakout palsu.
3. Memakai penjadwal yang lebih tepat waktu daripada GitHub Actions, dan
   menyimpan kode backtest sejak awal.
4. Memulai forward test lebih awal supaya sampelnya cukup untuk dibandingkan.

Semua perubahan ini baru akan saya uji dengan backtest dan forward test baru,
bukan dipasang ke bot yang sudah dibekukan.
