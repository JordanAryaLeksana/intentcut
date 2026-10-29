# Laporan Batch 1 — Typed AI Worker Dispatch

## A. Ringkasan

Batch 1 selesai pada branch `feat/m3-frontend`. Perubahan hanya mencakup registrasi tipe job, dispatch, pembatasan claim/recovery, dan regresi worker. Tidak ada implementasi Voice, Image, SAM, autentikasi baru, atau artefak turunan.

Tiga pipeline yang sudah ada sekarang diregistrasikan secara eksplisit:

| Tipe persisten | Handler | Kontrak hasil |
| --- | --- | --- |
| `uploaded_v1` | `RealAIProcessingAdapter` | `ProcessingResult` |
| `manual_v1` | `ManualRenderProcessor` | `ProcessingResult` |
| `revision_v1` | `RevisionProcessor` | `ProposalResult` |

Worker produksi tidak lagi mengirim tipe lain ke first-cut sebagai fallback. Job yang tidak didukung pool tidak di-claim dan tidak menghabiskan attempt. Recovery CLI menggunakan daftar kemampuan yang sama. Hasil handler juga diperiksa sebelum masuk ke jalur publikasi/completion.

Hasil final: Ruff lulus, **43 unit test lulus**, dan **131 integration/regression test lulus**; total **174 tes**, tanpa gagal atau skip pada run final.

## B. Arsitektur

### Sebelum perubahan

`worker_cli.py` mempunyai fungsi dispatch lokal dengan dua percabangan: manual render dan revision. Semua tipe lain jatuh ke first-cut. Claim normal mengambil job queued tanpa filter kemampuan; recovery normal juga tidak membatasi tipe.

Risikonya: typo pipeline atau job dari versi worker yang lebih baru dapat diambil worker yang salah, dikirim ke prosesor yang tidak sesuai, lalu gagal setelah attempt sudah terpakai.

### Sesudah perubahan

1. Saat bootstrap, CLI membentuk daftar `JobRegistration`.
2. `JobDispatcher` memvalidasi dan membekukan daftar itu.
3. Daftar `supported_job_types` dipakai dalam SQL claim sebelum row dikunci.
4. Dispatcher memeriksa kembali `pipeline_version` lalu memanggil satu handler yang tepat.
5. Dispatcher memastikan hasilnya sesuai kontrak tipe job.
6. `AIJobWorker` menggunakan mekanisme heartbeat, publikasi dan terminal transition yang sudah ada.
7. CLI memakai kemampuan dispatcher yang sama ketika memulihkan lease kedaluwarsa.

Alurnya:

`registrasi → filter SQL → claim lease → dispatch tepat → validasi hasil → completion ter-fence`

Lease adalah hak memproses sementara dengan token. Fencing adalah pemeriksaan yang menolak penulisan menggunakan token lama atau lease kedaluwarsa. Batch ini menambahkan pembatasan kemampuan sebelum claim/recovery; pemeriksaan ownership yang sudah ada tetap berlaku setelah pemrosesan.

### Komponen baru

- `JobType`: `StrEnum` dengan tiga nilai pipeline yang sudah dipakai database; tidak mengubah format tersimpan.
- `JobResult`, `JobHandler`, `JobResultType`: alias tipe untuk kontrak callable dan hasil.
- `JobRegistration`: dataclass frozen berisi tipe job, handler dan tipe hasil.
- `JobDispatcher`: registry yang menolak registrasi kosong, duplikat, handler non-callable, tipe tidak eksplisit, dan kontrak hasil yang salah.
- `supported_job_types`: tuple kemampuan untuk SQL claim/recovery.
- `requires_artifact_publisher`: memastikan registry yang menghasilkan media tidak dijalankan tanpa publisher.
- `_supported_pipeline_filter()`: validasi filter dan ekspresi SQL terhadap JSONB `request_payload.pipeline_version`.

Registry membekukan salinan registrasi. Mengubah list pembentuknya setelah bootstrap tidak mengubah kemampuan worker yang sedang berjalan. Ini mencegah daftar tipe claim berbeda dari handler yang tersedia.

### Kebijakan tipe yang tidak didukung

- Pada polling normal atau `--job-id`, job yang tidak cocok dengan kemampuan pool dilewati: tetap queued, token/attempt tidak berubah. Ini termasuk tipe masa depan, nilai malformed, dan job tanpa `pipeline_version`.
- Bila job tidak didukung sudah terlanjur mencapai dispatcher, dispatcher menolak sebelum handler dipanggil dengan kode aman `unsupported_job_type`. Worker hanya dapat merekam kegagalan melalui token lease yang masih sah.
- Job yang valid untuk pool lain juga dilewati, bukan ditandai gagal secara global.
- Tuple kemampuan kosong berarti tidak ada job yang boleh dipilih. Filter invalid menimbulkan `ValueError`, bukan berubah menjadi filter tanpa batas.
- `manual_only` adalah irisan dengan kemampuan registry, bukan cara melewati pembatasan registry.

## C. Perubahan file

Tabel ini hanya menunjukkan perubahan Batch 1, bukan seluruh dirty worktree dari milestone sebelumnya.

| Path | Perubahan | Tanggung jawab | Alasan |
| --- | --- | --- | --- |
| `src/intentcut/backend/jobs/dispatch.py` | Ditambah | Enum, registrasi immutable, routing dan validasi hasil | Menghapus fallback ambigu dan memberi satu sumber kemampuan worker |
| `src/intentcut/backend/worker_cli.py` | Diubah | Registrasi tiga handler dan filter recovery | Menyamakan bootstrap, eksekusi dan recovery tanpa memindahkan loop keluar konteks client |
| `src/intentcut/backend/ai_worker.py` | Diubah | Filter claim dari registry; pembungkus kompatibilitas adapter langsung; syarat publisher | Mencegah adapter produksi mengambil tipe yang salah sambil mempertahankan pola konstruksi lama |
| `src/intentcut/backend/storage/database.py` | Diubah | Parameter opsional `supported_job_types` pada claim/recovery | Menolak job tidak cocok di SQL sebelum lease/attempt berubah |
| `src/intentcut/backend/contracts.py` | Diubah | Tambahan kode error publik `unsupported_job_type` | Penolakan aman tanpa payload atau exception internal |
| `tests/unit/backend/test_job_dispatch.py` | Ditambah | Routing, konfigurasi, hasil salah, penolakan defensif | Membuktikan handler yang salah tidak dipanggil |
| `tests/unit/backend/test_worker_cli.py` | Diubah | Registrasi CLI, lifecycle client, filter recovery manual-only | Menguji wiring nyata, bukan hanya registry terpisah |
| `tests/integration/backend/test_typed_worker_dispatch.py` | Ditambah | Claim/recovery PostgreSQL dan fencing | Membuktikan token/attempt tidak berubah untuk job yang tidak cocok |
| `BATCH_1_TYPED_WORKER_DISPATCH.md` | Ditambah | Laporan dan bukti verifikasi | Dokumentasi untuk review batch |

Publisher artefak, renderer, model database, route API, frontend, dan file migrasi tidak diubah oleh Batch 1. File yang sudah dimodifikasi sebelum batch tetap dipertahankan.

## D. Skills dan dependensi

Instruksi `AGENTS.md` serta katalog skill yang tersedia diperiksa. **Tidak ada Codex skill yang digunakan untuk Batch 1.** Skill yang tersedia terutama berfokus pada UI/desain, produk OpenAI, dan pengelolaan skill/plugin; tidak ada yang memberi manfaat langsung untuk perubahan worker Meta/PostgreSQL ini. Tidak ada skill atau plugin yang dipasang.

Batch 1 tidak menambah atau menghapus dependensi proyek. Ada proses `uv add` dari giliran ekspansi sebelumnya yang ternyata selesai sebelum instruksi pembatasan batch diterima. Penambahan tersebut dibatalkan secara terarah menggunakan:

```sh
uv remove meta-sam-parser httpx
```

Paket tambahan yang dibatalkan: `meta-sam-parser==0.1.0`, `httpx==0.28.1`, serta transitif baru `certifi==2026.10.23` dan `httpcore==1.0.9`. Sesudah rollback, `git diff -- pyproject.toml uv.lock` kosong. Tidak ada implementasi yang memakai paket-paket itu dan tidak ada dependensi baru yang tersisa dari pekerjaan ini.

## E. Keputusan engineering

1. **Gunakan `pipeline_version` yang sudah tersimpan.** Tidak perlu kolom, tabel, atau migrasi baru untuk routing.
2. **Satu queue PostgreSQL tetap digunakan.** Queue/broker baru tidak membantu masalah pemilihan handler ini.
3. **Filter dilakukan sebelum claim.** Melempar error setelah handler salah berjalan sudah terlambat dan membuang attempt.
4. **Recovery ikut dibatasi.** Worker manual tidak seharusnya mengubah status/attempt budget job revision yang dimiliki pool lain.
5. **Tidak menandai semua tipe tidak dikenal sebagai failed.** Worker lama tidak boleh mematikan job yang seharusnya diproses worker versi baru.
6. **Kontrak hasil diperiksa.** First-cut/manual tidak boleh menyelesaikan job melalui jalur proposal, atau sebaliknya.
7. **Registrasi frozen saat bootstrap.** Batch berikutnya harus menambahkan tipe dan handler secara eksplisit; tidak ada hot registration yang dapat mengubah kemampuan saat lease sedang berjalan.
8. **Kompatibilitas adapter langsung dipertahankan.** `AIJobWorker` membungkus `RealAIProcessingAdapter`, `ManualRenderProcessor`, dan `RevisionProcessor` langsung ke registry satu tipe. Pemanggil lama tidak perlu mengganti bentuk konstruksinya.
9. **Dependency injection sintetis tetap kompatibel.** Callable biasa untuk fake/synthetic tests masih didukung. Ini bukan registrasi produksi baru; handler produksi tambahan wajib memakai `JobDispatcher`. API repository generik juga tetap mengizinkan filter `None` untuk caller lama/maintenance.
10. **Tidak ada fallback provider.** Tipe salah tidak dialihkan ke model lain atau memicu inferensi tambahan.

## F. Pengujian

### Ruff — lulus

```sh
uv run ruff check \
  src/intentcut/backend/jobs/dispatch.py \
  src/intentcut/backend/contracts.py \
  src/intentcut/backend/storage/database.py \
  src/intentcut/backend/ai_worker.py \
  src/intentcut/backend/worker_cli.py \
  tests/unit/backend/test_job_dispatch.py \
  tests/unit/backend/test_worker_cli.py \
  tests/integration/backend/test_typed_worker_dispatch.py
```

Hasil final: `All checks passed!`. Iterasi awal lint menemukan format baris panjang dan satu referensi filter yang keliru; keduanya diperbaiki sebelum verifikasi final. Pemeriksaan whitespace terfokus pada file Batch 1 juga lulus.

### Unit — 43 passed dalam 0,92 detik

```sh
uv run pytest \
  tests/unit/backend/test_job_dispatch.py \
  tests/unit/backend/test_worker_cli.py \
  tests/unit/backend/test_unit_ai_worker.py \
  -q --tb=short --basetemp=.pytest_tmp_batch1_unit
```

Output sementara run ini dipindahkan ke `/tmp` setelah tes agar tidak menambah sampah worktree.

### PostgreSQL/regresi — 131 passed dalam 43,27 detik

```sh
uv run pytest \
  tests/integration/backend/test_typed_worker_dispatch.py \
  tests/integration/backend/test_ai_worker.py \
  tests/integration/backend/test_ai_job_repository.py \
  tests/integration/backend/test_ai_artifact_repository.py \
  tests/integration/backend/test_uploaded_job_flow.py \
  tests/integration/backend/test_manual_editing.py \
  tests/integration/backend/test_revision_proposals.py \
  tests/integration/backend/test_ai_job_progress.py \
  -q --tb=short
```

Tes PostgreSQL menggunakan database test dengan schema unik yang dibuat/dihapus oleh fixture. Regresi lama mencakup pengujian migrasi idempotent dalam schema test tersebut; tidak ada migrasi yang diterapkan ke database development atau perubahan schema aplikasi untuk Batch 1.

### Bukti acceptance

- Ketiga tipe memanggil tepat satu handler yang sesuai.
- Normal CLI meregistrasikan tiga tipe; manual-only hanya `manual_v1`.
- Recovery CLI memakai tuple kemampuan yang sama dengan dispatcher.
- Callback pemrosesan dijalankan saat client OpenAI masih terbuka; manual-only tidak membangun client provider.
- Nilai unknown, kosong, beda kapitalisasi, angka, boolean, list, object, dan versi tanpa pipeline tidak menjadi fallback first-cut.
- Job di awal queue yang tidak kompatibel tidak menghalangi job kompatibel di belakangnya.
- Job yang dilewati tetap queued, `attempt_count=0`, dan tanpa lease/progress baru.
- Recovery manual tidak menyentuh revision lease yang kedaluwarsa.
- Lease lama tidak dapat memperbarui progress, menyelesaikan, menggagalkan, atau memublikasikan artefak setelah token diganti.
- Hasil handler dengan kelas salah ditolak sebelum completion/publikasi.
- Regresi first-cut, manual render, proposal acceptance, hash/artefak dan FFmpeg berjalan dengan provider mock dan media nyata.

Tidak ada paid inference atau browser test. Tidak ada frontend lint/build karena tidak ada perubahan frontend. Suite repository keseluruhan tidak diklaim sudah dijalankan.

## G. Kompatibilitas dan risiko

- Status job tetap `queued`, `running`, `succeeded`, `failed`; schema response dan progress tidak diubah.
- `unsupported_job_type` adalah penambahan kode aman. Frontend existing dapat memakai fallback pesan error generik.
- Aturan publikasi video/storyboard dan completion proposal tetap menggunakan implementasi lama.
- Heartbeat, token, durasi lease, batas retry, pemulihan attempt, transaksi completion dan penanganan commit tidak dirombak.
- Admission first-cut yang saat ini digunakan menyimpan `uploaded_v1`, sehingga tetap cocok dengan registry.
- Job legacy tanpa `pipeline_version` tidak dijalankan oleh worker registry. Bila ada job demikian di database development, diperlukan audit terpisah; tidak ada inferensi jenis berdasarkan `kind`.
- Job unknown/incompatible yang dilewati tetap queued sampai tersedia worker yang sesuai atau operator menanganinya. Ini keputusan kompatibilitas lintas versi, bukan klaim job sudah berhasil diproses.
- Jalur callable sintetis dan repository tanpa filter tetap ada untuk kompatibilitas pengujian/maintenance. Jaminan capability filtering produksi berlaku untuk CLI registry dan ketiga adapter produksi yang dikenali.
- Worker development yang sudah hidup tidak direstart dalam batch ini. Pengujian memverifikasi kode baru di proses test; penerapan ke proses worker aktif membutuhkan restart terkontrol setelah review.
- `git diff --check` seluruh worktree menemukan trailing whitespace yang sudah ada pada `shared/http_security.py`, di luar Batch 1. File itu tidak diubah. Pemeriksaan scoped Batch 1 bersih.
- Tidak ada autentikasi, pembatasan biaya, Voice, Image, atau SAM baru yang diklaim selesai.

Tidak ada reset repository, commit, push, atau migrasi ke database development.

## H. Batch berikutnya

Usulan Batch 2: kontrak hasil dan publikasi artefak turunan yang tetap lease-safe untuk JSON caption, image, dan video rendition. Batch itu perlu menentukan output yang diwajibkan setiap tipe tanpa memalsukan pasangan video/storyboard.

Batch 2 bergantung pada Batch 1 agar job dengan kontrak output baru hanya dapat diambil worker yang sudah memiliki handler dan publisher yang sesuai. Integrasi provider dan kontrol Studio baru tetap membutuhkan batch serta persetujuan terpisah.

**Batch 2 belum diimplementasikan. Berhenti untuk review pengguna.**
