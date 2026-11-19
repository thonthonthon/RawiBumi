# Berkontribusi

## Pengujian
```sh
.venv/bin/python -m pytest -q -n 8 tests/unit
cd apps/web && npm run verify        # tipe hasil generasi, batas, pemeriksaan tipe, uji unit, build, gerbang desain
cd apps/web && npx playwright test   # uji peramban terhadap demo di peramban
```
Sebagian uji memerlukan riwayat pengembangan atau bukti privat dan dilewati dengan alasan tertulis pada salinan publik.

## Aturan
- Keputusan teknik tetap di tangan pengguna: saran dan pemeriksaan, tidak pernah perubahan diam-diam.
- Jangan menyetel mesin agar mendekati PVsyst; perbedaan dengan alasan yang kuat dapat diterima.
- Jangan menyertakan data cuaca atau komponen yang tidak boleh Anda sebarkan ulang.
- Perubahan yang mengubah hasil harus dijelaskan alasannya, dengan uji yang menunjukkannya.

## Mengusulkan perubahan
Buka issue yang menjelaskan masalah, buktinya (berkas proyek atau langkah untuk mereproduksi) dan hasil yang diharapkan.
