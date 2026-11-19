# Metode dan batasan mesin

## Yang didukung bukti
- Jalur standar per jam menerapkan metode yang dirujuk dengan benar (tinjauan fisika seluruh mesin oleh peninjau AI terpisah yang menghitung ulang setiap tahap (internal, 2026; rinciannya tidak dipublikasikan)).
- Hasil diperiksa secara internal terhadap PVsyst 8 pada dua proyek nyata yang terbayangi, dengan kesesuaian dekat pada energi tahunan dan bulanan (rinciannya tidak dipublikasikan: proyek klien). PVsyst adalah pembanding, bukan kebenaran mutlak: kesesuaian menunjukkan konvensi yang sama,
  bukan ketepatan lapangan.
- Model modul diperiksa secara internal terhadap daya STC lembar data pada sekumpulan berkas PAN nyata (rinciannya tidak dipublikasikan).
- Neraca energi seimbang di setiap interval setiap simulasi, atau simulasi gagal.
- Dua simulasi identik memberi angka identik; hanya pengenal per simulasi yang berbeda dalam paket tersimpan.

## Yang tidak diklaim
1. Ketepatan terhadap pembangkit terukur: belum ada data lapangan yang dipakai.
2. Bahwa kesesuaian dengan PVsyst berlaku umum: dua proyek, satu iklim, modul kristalin, data per jam.
3. Hasil orientasi campuran terhadap acuan luar (belum ada acuannya).
4. Ketidakcocokan listrik akibat bayangan tidak merata pada jalur standar.
5. Perilaku termal inverter, atau operasi di luar jendela MPPT sebagai prediksi fisik (string seperti itu memblokir simulasi).
6. Bayangan horizon jauh (belum ada masukan profil horizon).
7. Simulasi di bawah satu jam, daya reaktif, faktor daya atau batas kVA.
8. Bahwa rugi-rugi bawaan menggambarkan lokasi nyata: itu nilai awal rekomendasi untuk ditinjau.
9. Zona waktu dengan waktu musim panas.

## Aturan keselamatan dalam pemeriksaan desain
String dengan tegangan rangkaian terbuka saat dingin di atas tegangan DC maksimum inverter memblokir simulasi, begitu
pula string yang tegangan operasinya keluar dari jendela MPPT. Ini aturan desain, bukan rugi yang dimodelkan.

## Bawaan LID

Proyek baru memakai recommended_defaults.v2: isian LID pengguna berlaku untuk semua sirkuit; jika tidak ada, setiap sirkuit memakai fraksi LID berkas modul yang terhingga dalam [0, 1). Nilai yang hilang atau tidak valid memakai nilai awal generik: 0,5 % untuk teknologi TOPCon, HJT, heterojunction atau IBC; 1,5 % untuk silikon kristalin lainnya dan teknologi tidak diketahui; 0 % untuk film tipis. Ini nilai awal, bukan pengukuran: periksa lembar data. Kosongkan isian untuk memulihkan LID otomatis. Setiap simulasi mencatat nilai dan sumber per sirkuit. Proyek v1 tetap memakai LID 0 % kecuali diubah pengguna; “Gunakan bawaan terkini” beralih ke v2 dalam satu penyimpanan yang dapat dibatalkan, dengan mempertahankan isian pengguna. Hasil tersimpan tidak berubah.
