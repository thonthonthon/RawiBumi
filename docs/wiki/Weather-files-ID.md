# Berkas cuaca

| Format | Dibaca | Catatan |
|---|---|---|
| Penyedia bawaan | Ya | Data per jam setahun berbasis ERA5 untuk lokasi. |
| TMY3 (`.csv`) | Ya | Berkas tahun tipikal (misalnya ekspor TMY3 dari Meteonorm). |
| EPW | Ya | Cuaca EnergyPlus. Header lokasi yang terpotong ditolak dengan alasan. |
| CSV Standar PVsyst | Ya | Format yang dipakai pembandingan PVsyst dari awal sampai akhir. |
| `.dat` Meteonorm dengan header | Ya | Hanya acuan waktu −30 menit; acuan lain ditolak dengan alasan. |
| CSV RawiBumi | Ya | Nilai kosong (`nan`, kosong) masuk pemeriksaan kualitas; nilai tak hingga dan cap waktu berulang ditolak. |
| `.MET` PVsyst | Tidak | Ekspor CSV "PVsyst Standard" dari PVsyst. |
| `.dat` Meteonorm tanpa header, atau tata letak `.dat` "PVsyst" dari Meteonorm | Tidak | Ekspor TMY3 dari Meteonorm. |

Setiap impor menampilkan periode, langkah waktu, zona waktu, jarak dari lokasi dan pemeriksaan kualitas sebelum
disimpan. Hanya jalur CSV PVsyst yang diperiksa dari awal sampai akhir terhadap acuan luar; pengimpor lain dicakup uji unit.
