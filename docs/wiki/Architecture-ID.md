# Arsitektur

| Folder | Isi |
|---|---|
| `apps/api` | Layanan FastAPI: proyek, perintah geometri dan kelistrikan, riwayat (urungkan), impor, studi, laporan. |
| `apps/web` | Aplikasi peramban React (tampilan denah, 3D dan SLD, sepuluh langkah), mode demo, dan perender laporan. |
| `engine` | Simulasi: iradiansi dan transposisi, optik, modul (satu dioda), inverter, rugi-rugi, simulasi per jam. |
| `geometry` | Model dan penyuntingan geometri, pengisian field PV, 3D, dan geometri bayangan dekat. |
| `shading` | Bayangan langsung, difus dan albedo, serta bayangan listrik. |
| `electrical` | String, MPPT, penyuntingan topologi, kabel DC dan AC. |
| `components` | Pembacaan dan pemetaan PAN dan OND, kandidat, pemeriksaan acuan IV. |
| `weather` | Pengimpor (TMY3, EPW, Meteonorm, CSV PVsyst, CSV RawiBumi), penyedia, pemeriksaan kualitas. |
| `reporting` | Grafik, ekspor PDF terlindungi, templat. |
| `validation` | Pemeriksaan teknik, perkakas pembandingan PVsyst, atribusi. |
| `schemas` | Skema JSON model data kanonik. |

Prinsip: insinyur yang memutuskan (otomasi menyarankan dan memeriksa, tidak pernah mengubah diam-diam); setiap simulasi
terikat pada revisi proyek, komponen, cuaca dan model yang tidak berubah; format luar adalah adaptor ke model data RawiBumi.
