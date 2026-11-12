# Refleksi: Backtest vs Forward

Hafiz Alfarisi, NIM 25110200002, Kelas Trad1

Angka di bawah diambil dari dashboard per 12 Nov 2026. Angka final ada di
`hasil_forward.json`, `hasil_backtest.json`, dan `hasil_kecocokan.json`.

## 1. Apa hasilnya

| | Backtest (3 tahun, 13 Nov 2023 - 12 Nov 2026) | Forward (10 Nov 2026 sampai sekarang) |
|---|---|---|
| Return | -97,37% | -0,28% |
| Max drawdown | -97,41% | lihat dashboard |
| Jumlah trade | 1.706 | 3 trade tertutup (6 order) |
| Buy and hold BTC/IDR | +129,56% | lihat dashboard (jendela yang sama) |

Strategi saya **rugi besar di backtest**. Saya tidak mengubah aturan supaya
hasilnya bagus, karena aturan sudah dibekukan sebelum forward test dimulai.

## 2. Kenapa strategi ini rugi

Penyebab utamanya adalah **biaya**, bukan sinyal yang selalu salah.

- Satu putaran beli-lalu-jual kena fee sekitar 0,83% (0,41555% x 2), belum
  termasuk spread dan slippage.
- Breakout Donchian 20/10 pada data 1 jam menghasilkan sangat banyak trade
  (1.706 trade). Win rate hanya sekitar 22% dan profit factor sekitar 0,52.
- Total biaya (fee + spread + slippage) kira-kira **3,4 kali lipat laba kotor**
  sebelum biaya. Artinya, sekalipun sinyalnya punya sedikit keunggulan, biaya
  memakannya habis. Ini overtrading.
- Buy and hold BTC/IDR di periode yang sama naik +129,56%, jadi pasarnya
  sendiri tidak buruk. Yang buruk adalah cara bot masuk-keluar terlalu sering.

Pelajaran: strategi dari UTS dibuat untuk data harian saham, dengan trade yang
jarang. Saat dibawa ke kripto 1 jam, jumlah trade naik berkali-kali lipat
sementara biaya per trade tetap, sehingga biaya mengalahkan keunggulan sinyal.

## 3. Apakah forward cocok dengan backtest?

**Sinyal: cocok.** Pada jendela forward, sinyal bot sama dengan sinyal backtest
untuk 117 dari 117 candle yang dibandingkan (100%). Karena `signal()` yang
dipakai bot dan backtest adalah fungsi yang sama dari `signal_strategy.py`,
hasil ini memang yang diharapkan. Ini bukti bahwa tidak ada perbedaan logika
antara backtest dan bot.

**Eksekusi: ada selisih kecil.** Pada jendela yang sama, return backtest -1,76%
dan return forward bot -0,28%. Selisih itu datang dari harga fill, bukan dari
sinyal:

- Backtest mengisi order di **open candle berikutnya**. Bot baru berjalan
  beberapa puluh menit setelah candle tutup, karena GitHub Actions terlambat.
  Selisih harga karena keterlambatan itu terlihat di tabel dashboard
  ("Dari keterlambatan jadwal"), berkisar dari sekitar -0,6% sampai +0,3%
  per trade, bisa menguntungkan atau merugikan.
- Selisih akibat spread dan slippage bot kecil (di bawah sekitar 0,1% per
  fill), karena bot mengisi order dengan menelusuri order book.
- Hanya ada 3 trade tertutup. Dengan sampel sekecil itu, perbandingan return
  tidak bisa dibaca sebagai bukti statistik. Satu fill yang berbeda sedikit
  saja bisa menggeser hasilnya.

Kesimpulan: **sinyal identik, eksekusi berbeda sedikit karena waktu dan order
book, dan sampel forward terlalu pendek untuk menilai profitabilitas.**

## 4. Hal yang tidak berjalan baik

- **Uptime.** Beberapa jam terlewat, sehingga ada 18 pasangan-candle yang tidak
  diproses bot di jendela perbandingan. Penyebabnya penjadwal GitHub Actions
  yang sering terlambat atau melewatkan jam. Saya menambah jadwal cadangan
  (menit ke-27 dan ke-47) pada 12 Nov. Ini tercatat di README sebagai perubahan
  infrastruktur, bukan perubahan aturan. Saya tidak menghapus atau menyunting
  log yang sudah ada.
- **Mulai terlambat.** Saya baru mengerjakan pada 9 Nov. Dosen mengizinkan
  forward test dengan waktu yang tersedia, jadi forward test saya hanya
  beberapa hari. Itu terlalu pendek untuk menyimpulkan apa pun soal performa.
- **Kode backtest awal tidak tersimpan.** Saya menulis ulang `backtest.py` dan
  mencocokkan hasilnya dengan angka lama (-97,37% vs -96,72%). Selisihnya kecil
  dan versi baru yang saya pakai sebagai versi resmi.
- **Estimasi biaya backtest.** Biaya per sisi backtest ditaksir dari snapshot
  order book sebelum freeze. Untuk XRP/IDR snapshot-nya sedikit, sedangkan
  median spread XRP di forward ternyata 0,0888%, lebih lebar dari BTC (0,0241%)
  dan ETH (0,0312%). Jadi taksiran biaya XRP di backtest kurang kuat.

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
