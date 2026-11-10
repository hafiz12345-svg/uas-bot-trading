# Fungsi sinyal strategi breakout.
# Dipakai oleh backtest DAN bot, jangan ubah setelah freeze.

N_MASUK = 20   # close > tertinggi 20 jam sebelumnya -> BUY
N_KELUAR = 10  # close < terendah 10 jam sebelumnya -> SELL


def signal(closes, punya_posisi):
    """closes: harga close urut lama -> baru, hanya dari candle yang sudah tertutup."""
    if len(closes) < N_MASUK + 1:
        return "HOLD"
    sekarang = closes[-1]
    if not punya_posisi:
        if sekarang > max(closes[-N_MASUK - 1:-1]):
            return "BUY"
    else:
        if sekarang < min(closes[-N_KELUAR - 1:-1]):
            return "SELL"
    return "HOLD"
