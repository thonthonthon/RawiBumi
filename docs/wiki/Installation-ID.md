# Instalasi

RawiBumi berjalan di Linux (atau WSL di Windows) dengan **Python 3.12** dan **Node.js 22**. Laporan PDF juga memerlukan
Chromium yang dipasang oleh Playwright (`cd apps/web && npx playwright install chromium`) dan pengaturan di bagian
*Self-hosting* README, yang juga memuat skrip mulai.

## 1. Ambil kode dan pasang
```sh
git clone https://github.com/thonthonthon/RawiBumi.git
cd RawiBumi
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --only-binary=:all: -r requirements.lock
cd apps/web && npm ci && cd ../..
```
`requirements.lock` mengunci setiap paket Python beserta hash SHA-256 untuk Python 3.12 di Linux x86_64. Platform lain
memerlukan kunci tervalidasi sendiri. `npm ci` memasang tepat isi `apps/web/package-lock.json`.

## 2. Jalankan
**Untuk dipakai** (satu proses, satu port):
```sh
cd apps/web && npm run build && cd ../..
.venv/bin/uvicorn apps.api.server:app --host 127.0.0.1 --port 8000
```
Buka <http://127.0.0.1:8000>. API menyajikan aplikasi web yang sudah dibangun.

**Untuk pengembangan** (muat ulang otomatis): jalankan API seperti di atas, lalu di terminal kedua
`cd apps/web && npm run dev`, dan buka <http://127.0.0.1:5173>. Server pengembangan meneruskan `/api` ke port 8000.
Jangan pernah membukanya ke jaringan.

## 3. Lokasi data Anda
Proyek disimpan di `var/projects/` (atur `RAWIBUMI_PROJECT_STORE` untuk memindahkannya). Cuaca, hasil, citra dan
pustaka komponen berada di samping folder itu. Cadangkan `var/` untuk mencadangkan pekerjaan Anda.

## Pembaruan
Hasil yang tersimpan mempertahankan angkanya. Menjalankan ulang proyek lama memakai model dan rugi-rugi rekomendasi
terkini, sehingga hasil dapat berubah. Hasil yang disimpan sebelum ada sidik desain perlu dijalankan ulang agar dapat
membuat laporan.
