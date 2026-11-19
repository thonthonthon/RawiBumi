# Cara kerja RawiBumi

*English: [How RawiBumi works](How-RawiBumi-works).*

Halaman ini menjelaskan apa yang terjadi antara desain Anda dan angka di Hasil: rantai perhitungan, metode di setiap
langkah, pustaka yang dipakai RawiBumi, cara pengujiannya, apa yang sudah dan belum berjalan, serta kebiasaan yang
perlu diketahui. Untuk klaim yang didukung dan tidak didukung bukti, lihat
[Metode dan batasan mesin](Engine-methods-and-limits-ID).

## Rantai perhitungan, jam demi jam

Setiap simulasi menghitung satu tahun (atau periode berkas cuaca) pada langkah waktu berkas cuaca, biasanya satu jam.
Setiap langkah mencatat model yang dipakai, sehingga audit hasil menunjukkan persis apa yang dilakukan.

| # | Langkah | Metode | Catatan |
|---|---|---|---|
| 1 | Garis waktu | Setiap interval diwakili titik tengahnya (atau konvensi yang dinyatakan berkas) | Hanya zona waktu tanpa daylight saving |
| 2 | Posisi matahari | NREL Solar Position Algorithm (SPA), melalui pvlib | Memakai elevasi, tekanan dan suhu lokasi bila ada |
| 3 | Iradiasi yang hilang | Bila berkas tidak memuat DNI atau DHI: dekomposisi Erbs, DISC atau DIRINT (pvlib) | Nilai pelengkap ditandai dalam pemeriksaan mutu |
| 4 | Bidang modul | Transposisi anisotropik Perez (per jam), dengan komponen langsung, sirkumsolar, langit isotropik, horizon dan pantulan tanah dipisah; Perez–Driesse, Hay–Davies dan isotropik juga tersedia | Pantulan tanah Lambertian dengan satu albedo (bawaan 0,2) |
| 5 | Bayangan dekat | Adegan 3-D (atap, penghalang, modul itu sendiri) dijadikan mesh; sinar langsung ditelusuri dari tiap penerima ke arah matahari; difus langit ditimbang pada kubah langit (akurasi standar: 48 sektor azimut × 12 pita elevasi); pita horizon dan pandangan tanah adalah kanal terpisah | Bayangan diterapkan per kanal, sebelum rugi sudut |
| 6 | Sudut datang (IAM) | Tabel IAM modul dari berkas PAN bila ada; bila tidak, model Fresnel/fisik (n = 1,526, K = 4, L = 0,002) | Faktor IAM difus diintegrasikan atas langit, horizon dan tanah |
| 7 | Kotoran (soiling) | Fraksi bulanan (bawaan 3 % tiap bulan) pada hasil optik | Dapat diubah per bulan |
| 8 | Suhu sel | Kesetimbangan panas tunak gaya PVsyst (`Uc`, `Uv`, absorptansi), melalui pvlib; bawaan pemasangan semi-terintegrasi `Uc = 20`, `Uv = 0` W/m²K | Efisiensi modul dalam kesetimbangan panas diselesaikan dengan iterasi titik tetap singkat |
| 9 | Kelistrikan modul | Model dioda tunggal PVsyst (pemetaan parameter versi 6) dari data PAN modul, digerakkan oleh iradiasi efektif setelah IAM dan suhu sel | Setiap modul dalam satu string dianggap menerima iradiasi dan suhu yang sama (lihat batasan) |
| 10 | String dan MPPT | Modul seri, string paralel, bekerja di titik daya maksimum MPPT di dalam jendela tegangannya | String di luar jendela atau di atas batas tegangan dingin memblokir simulasi sebagai kesalahan desain |
| 11 | Rugi larik | LID (dari berkas modul, atau nilai generik menurut teknologi), mutu modul (dari toleransi PAN), ketidakcocokan modul dan string (nilai rekomendasi menurut panjang dan jumlah string), degradasi (tahun pertama = setengah tahun dari laju tahunan) | Setiap sirkuit (MPPT) ditangani terpisah |
| 12 | Kabel DC | Rugi ohmik per sirkuit dari fraksi pada STC (bawaan 1,5 %), diterapkan sebagai I²R pada arus operasi | |
| 13 | Inverter | Kurva efisiensi OND inverter, bergantung tegangan; batas arus dan daya MPPT; ambang daya dan tegangan DC; batas daya AC (clipping); konsumsi malam dan siaga | |
| 14 | Sisi AC | Kabel AC per inverter (kuadratik terhadap daya), trafo opsional (rugi besi dan tembaga), ketidaktersediaan, kabel AC pembangkit, batas zero export opsional | Mati atau nol kecuali Anda mengaturnya |
| 15 | Hasil | Energi di titik sambung, hasil spesifik, rasio kinerja (gaya IEC 61724: energi ÷ kWp ÷ iradiasi bidang modul), diagram rugi, deret bulanan dan per jam, tabel inverter dan MPPT | Setiap rugi tercatat di buku besar energi yang harus seimbang tiap jam, atau simulasi gagal |
| 16 | P50–P95 | Buku besar ketidakpastian — variasi matahari antartahun, bias sumber daya matahari, galat model sisa, ketidakpastian komponen dan ketersediaan, beserta korelasinya — digabung menjadi nilai probabilitas terlampaui | Metode sederhana: tahun simulasi diperlakukan sebagai rata-rata tahunan; komponen dan sumbernya tercantum bersama hasil |

### Pilihan di luar jalur standar
- **Orientasi campuran:** satu inverter boleh melayani bidang dengan kemiringan atau azimut berbeda; hasil dilaporkan
  per kelompok orientasi.
- **Bayangan elektris terperinci (level 2, substring bypass):** untuk larik yang terbayangi, jalur opsional ini
  memodelkan ketidakcocokan di dalam string pada tingkat dioda bypass. Lebih lambat dan memakai pilihan yang
  disematkan; jalur standar tidak memodelkan ketidakcocokan elektris akibat bayangan tak merata.

## Cara pengujiannya
- Audit independen jalur standar per jam terhadap metode yang dikutip.
- PVsyst 8 pada dua proyek nyata yang terbayangi: energi jaringan tahunan dalam −0,06 % dan −0,30 %; bulan terburuk
  dalam −0,12 % dan −0,46 %. PVsyst adalah pembanding, bukan kebenaran.
- Model modul: daya STC datasheet terulang dalam ±0,7 % pada 63 berkas PAN nyata (median +0,03 %).
- Keterulangan: dua simulasi identik memberi angka identik.
- Sekitar 8.300 uji Python dan 1.600 uji unit peramban, ditambah uji ujung-ke-ujung peramban terhadap mesin sungguhan.
- Belum: pembandingan dengan data pembangkit terukur.

## Pustaka yang dipakai
**Mesin (Python 3.12):** pvlib (posisi matahari, dekomposisi, transposisi, IAM, termal), NumPy, pandas dan SciPy
(larik, deret waktu, pemecah), Shapely (geometri 2-D), PyArrow (menyimpan hasil per jam), h5py, lxml dan PyYAML
(format cuaca dan komponen), FastAPI, Starlette, Uvicorn dan Pydantic (API web lokal), jsonschema (validasi proyek),
pikepdf (laporan PDF), pytest (pengujian).

**Aplikasi web (TypeScript, React):** React dan Zustand (antarmuka dan state), three.js (tampilan 3-D), MapLibre GL
(peta latar), ECharts dan uPlot (grafik), TanStack Table dan Virtual (tabel besar), React Aria Components dan cmdk
(kontrol yang aksesibel, palet perintah), i18next (Inggris dan Indonesia), Vite, Vitest dan Playwright (build dan uji).

Versi persis dikunci di `requirements.lock` (dengan hash) dan `apps/web/package-lock.json`; lisensi pihak ketiga ada
di `apps/web/THIRD_PARTY_NOTICES.md`.

## Apa yang sudah dan belum berjalan
**Berjalan dari awal sampai akhir:** lokasi dan peta, atap dan penghalang, pengisian tata letak PV, impor komponen
(PAN/OND), sistem dan ukuran inverter, string (disarankan atau manual), cuaca (unduh ERA5 atau impor berkas), rugi-rugi,
simulasi per jam dengan bayangan dekat, hasil, laporan (HTML dan PDF), CSV 10 kolom dan berkas proyek, undo dan
cadangan, satu jendela dengan tampilan Atas/Depan/Belakang/Kiri/Kanan/Isometrik/tegak lurus bidang, serta titik
acuan sembilan titik untuk tiap atap, penghalang dan zona larangan (posisi dari titik asal, orientasi, ukuran menurut
sumbu sendiri).

**Belum (sedang dikerjakan):** lihat "Known work in progress" di README: alat menyunting hanya bekerja di tampilan
Atas (tampilan lain untuk memilih, menggeser dan menaikkan); bangunan dengan beberapa atap belum bergerak sebagai satu
kelompok di sekitar titik acuan bersama; pegangan ubah ukuran di kanvas masih mengikuti sumbu peta. Batasan mesin (belum dibandingkan dengan
pembangkit terukur, tanpa horizon jauh, hanya per jam, tanpa daylight saving, tanpa daya reaktif) ada di
[Metode dan batasan mesin](Engine-methods-and-limits-ID).

## Kebiasaan yang perlu diketahui
- **Iradiasi ERA5 cenderung tinggi di daerah tropis berawan.** Data setahun dari ERA5 (Open-Meteo) bisa 10–15 % di
  atas data stasiun di tempat seperti Jakarta. Bandingkan dengan data lokal sebelum mengandalkan hasilnya.
- **Rasio kinerja bergantung pada apa yang Anda aktifkan.** LID, kabel AC, trafo dan ketidaktersediaan bernilai 0 atau
  mati secara bawaan, kecuali LID pada proyek baru; simulasi tanpa itu terbaca beberapa poin lebih tinggi daripada
  laporan PVsyst yang umum.
- **Bawaan rugi-rugi berversi.** Proyek baru memakai bawaan terkini (LID otomatis); proyek lama tetap memakai bawaan
  sebelumnya (LID 0 %) sampai Anda menekan "Gunakan bawaan terkini" di Rugi-rugi & jaringan. Hasil tersimpan tidak
  pernah berubah.
- **Undo bertahan selama server berjalan** (10 langkah per proyek). Memulai ulang server menghapusnya; cadangan tidak.
- **Satu pengguna dalam satu waktu.** Tidak ada akun; dua orang yang menyunting proyek yang sama sekaligus saling
  menimpa langkah yang belum tersimpan.
- **Mengatur ulang string sebuah inverter membebaskan string lamanya.** Menerapkan tata letak MPPT baru (Sistem atau
  Kelistrikan) menghapus string inverter yang tidak dipertahankan, dan modulnya bebas untuk string baru.
- **Hapus selalu meminta konfirmasi dan menyebut nama objeknya.** Periksa nama di dialog sebelum mengonfirmasi.
- **Simulasi panjang di balik proxy.** Proxy yang memutus permintaan panjang (misalnya 100 detik) memerlukan
  `RAWIBUMI_SIMULATE_WAIT_SECONDS`; aplikasi lalu memantau simulasi alih-alih menunggu satu permintaan.
- **Laporan PDF memerlukan pengaturannya** (lihat bagian Self-hosting di README); tanpa itu hanya laporan HTML yang
  tersedia.
- **Platform:** kunci Python untuk Linux x86_64; di Windows gunakan WSL 2.
