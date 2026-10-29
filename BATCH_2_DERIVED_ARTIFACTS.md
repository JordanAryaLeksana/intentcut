# Batch 2 — Lease-Safe Derived Artifact Infrastructure

## A. Ringkasan dan batas implementasi

Batch 2 menyediakan kontrak, validasi, publikasi, persistence metadata, dan download
untuk satu caption JSON, image PNG/JPEG, atau video rendition MP4 per job.
Tidak ada inference, endpoint admission fitur multimodal, handler provider, frontend,
transkripsi, subtitle burning, image generation AI, SAM, atau perubahan EditPlan.
ProcessingResult dan ProposalResult tetap dipakai oleh pipeline sebelumnya.

## B. Audit dan arsitektur sebelum/sesudah

Sebelumnya pasangan video/storyboard diwajibkan di:

1. AIArtifactPublisher.publish_and_complete: dua sumber tetap.
2. Database.complete_ai_job_with_artifacts: persis dua kind dalam satu transaksi.
3. AIJobArtifact: constraint kind hanya video/storyboard dan unique(job_id,kind).
4. AIJobService.snapshot, response schema, dan SnapshotResponse: hanya dua format.

Sesudah perubahan, jalur legacy tetap memerlukan pasangan tersebut. Jalur derived
memerlukan persis satu output sesuai pipeline_version yang eksplisit. Tidak ada
fallback ke video atau pembuatan storyboard palsu. Proposal tetap mempunyai jalur
completion sendiri. Ketiga tipe baru belum didaftarkan ke CLI produksi: batch
berikutnya harus menyediakan handler yang nyata dan registrasi eksplisit.

Alur derived:

JobDispatcher → handler bertipe → AIJobWorker + heartbeat → publisher staging →
validasi parent dan konten → publish + checksum + fsync → transaksi PostgreSQL
INSERT artifact dan fenced success → API listing dan verified-snapshot download.

Semua media I/O dan subprocess berjalan di luar transaksi completion. Transaksi
mengunci job, memeriksa running/token/expiry, memeriksa output dan parent, INSERT,
kemudian memeriksa expiry lagi sebelum transisi succeeded. Tidak ada queue baru.

## C. Inventaris file Batch 2

Status di sini relatif terhadap awal Batch 2; beberapa file Modified sudah
untracked/modified dari milestone sebelumnya. Tidak ada file yang dihapus.

| Path | Status | Tanggung jawab dan alasan |
|---|---|---|
| src/intentcut/backend/artifacts/derived.py | Added | Result types, parent identity, schema caption, MIME allowlist, validasi image lokal |
| src/intentcut/backend/ai_artifacts.py | Modified | Publikasi satu output derived, validasi lineage, rekonsiliasi commit dengan metadata baru |
| src/intentcut/backend/ai_job_service.py | Modified | Verified snapshot untuk caption/image/rendition tanpa mengekspos path |
| src/intentcut/backend/ai_worker.py | Modified | Routing hasil derived ke publisher; heartbeat/proposal/legacy tetap |
| src/intentcut/backend/artifacts/routes.py | Modified | Content type/extension eksplisit, lineage opsional, unknown kind ditolak |
| src/intentcut/backend/artifacts/schemas.py | Modified | Kind tambahan dan metadata publik yang aman |
| src/intentcut/backend/jobs/dispatch.py | Modified | Tiga pipeline/result registration contracts eksplisit, publisher diwajibkan |
| src/intentcut/backend/storage/database.py | Modified | Completion derived atomik, parent project lookup, shared fenced transaction |
| src/intentcut/backend/storage/database_models.py | Modified | Tiga kolom nullable, parent FK, constraint kind/lineage/content type |
| scripts/migrations/004_derived_artifacts.sql | Added | Migrasi eksplisit dan idempotent, tanpa tabel baru |
| tests/unit/backend/test_derived_artifacts.py | Added | Schema, tipe dispatch, image bounds, unknown types |
| tests/unit/backend/test_job_dispatch.py | Modified | Mempertahankan regresi tiga pipeline lama setelah enum bertambah |
| tests/integration/backend/test_derived_artifacts.py | Added | PostgreSQL/FFmpeg/HTTP, fencing, concurrency, recovery, migration |
| BATCH_2_DERIVED_ARTIFACTS.md | Added | Kontrak, keputusan, evidence, batas rollout |

## D. Kontrak, model, dan fungsi

- ArtifactParent(artifact_id: UUID, sha256: str): immutable reference dengan hash
  lowercase 64 karakter; tidak menerima URL/path.
- CaptionArtifactResult(path, parent), ImageArtifactResult(path, parent=None),
  VideoRenditionResult(path, parent): path hanya dipakai internal worker.
- CaptionCue, CaptionDocument, validate_caption: schema strict, unknown fields
  ditolak; timestamp segmen integer ms, bukan klaim word-level timing.
- image_content_type dan validate_image: signature, codec, dimensi, jumlah frame,
  serta decode sebenarnya; MIME tidak dipercaya dari ekstensi nama file.
- Database.get_project_artifact: lookup hanya pada project yang sama dan job
  penghasil yang sudah succeeded.
- Database.complete_derived_artifact: hanya satu output dengan kind/MIME eksplisit.
- Database._complete_artifacts: transaksi bersama dengan legacy; wrapper legacy
  tetap mengharuskan dua artifact.
- Publisher._validate_parent: lookup project, copy bounded lewat secure storage,
  verifikasi SHA dan ukuran; probe parent video untuk durasi caption.
- Publisher._reconcile: membandingkan seluruh identitas, termasuk parent dan MIME,
  setelah exception commit yang hasilnya tidak pasti.

### Kontrak job internal untuk handler batch berikutnya

| pipeline_version | Result | Artifact kind | Parent |
|---|---|---|---|
| caption_artifact_v1 | CaptionArtifactResult | captions | Wajib: video/rendition |
| image_artifact_v1 | ImageArtifactResult | image | Opsional: video/rendition/image |
| video_rendition_v1 | VideoRenditionResult | rendition | Wajib: video/rendition |

Snapshot request job harus berisi parent_artifact_id (string UUID) dan
parent_sha256 yang persis sama dengan output, bila parent ada. Untuk image tanpa
parent kedua nilai absen/null. Producing job melalui job_id; project melalui
AIJob.project_id. Tidak ada project/user ownership baru yang diada-adakan.

Caption JSON minimal (contoh schema, bukan hasil transkripsi):

```json
{"schema_version":"captions-v1","duration_ms":250,"cues":[]}
```

Cue: start_ms >= 0, end_ms > start_ms, text nonblank maksimal 2000 karakter,
speaker opsional maksimal 80 karakter. Maksimal 5000 cue dengan start terurut,
end tidak melampaui duration_ms; overlap boleh untuk ucapan bersamaan. Dokumen
maksimal 1 MiB dan duration_ms maksimal 24 jam. Saat publikasi, durasi harus cocok
dengan parent hasil FFprobe dalam toleransi 50 ms. Cue kosong diperbolehkan;
validator ini tidak melakukan deteksi suara/silence.

Image: PNG/JPEG statis, maksimal 16 MiB, sisi maksimal 8192, maksimal 16.777.216
pixel, satu frame decoded, decode FFmpeg wajib berhasil. GIF/WebP/SVG/animasi
tidak didukung di batch ini. Semua limit juga dibatasi storage.max_file_bytes.
Video rendition: MP4 valid menggunakan validator FFprobe/FFmpeg legacy dan batas
byte storage. Tidak mengklaim mempunyai manifest cut/frame baru. Manifest M3.4
pada storyboard manual-render tidak berubah.

### API retrieval

Endpoint tetap:

- GET /projects/{project_id}/ai-jobs/{job_id}/artifacts
- GET /projects/{project_id}/ai-jobs/{job_id}/artifacts/{artifact_id}

Listing derived menambahkan content_type, parent_artifact_id, parent_sha256 saat
ada. Field null dikecualikan sehingga listing legacy mempertahankan bentuknya.
Download memakai application/json, image/png, image/jpeg, atau video/mp4 sesuai
hasil validasi, nama attachment UUID dengan ekstensi benar, private/no-store dan
nosniff. File di-copy ke snapshot privat, diverifikasi ukuran/hash sebelum byte
response dikirim. Tidak ada storage_key/path/URL provider di response.

## E. Skill dan dependensi

AGENTS.md root dan katalog skill tersedia telah diperiksa. Tidak ada instruksi
AGENTS tambahan di src/tests/scripts. Tidak menggunakan skill: katalog tidak
menawarkan skill backend artifact/PostgreSQL/lease yang relevan; skill UI tidak
sesuai perubahan backend ini. Tidak menginstal skill/plugin/package. Tidak ada
perubahan pyproject.toml atau uv.lock. Pydantic, PostgreSQL, FFmpeg/FFprobe dan
storage yang sudah ada digunakan kembali.

## F. Keputusan engineering

- Tiga dataclass konkret dan allowlist, bukan generic plugin framework.
- Kolom pada tabel artifact lama, bukan tabel/event queue baru. Dibutuhkan karena
  constraint lama menolak kind baru dan belum ada tempat menyimpan lineage/MIME.
- Kind rendition dibedakan dari video legacy agar kontrak pasangan tidak ambigu.
- Parent image boleh null untuk generation murni; caption dan rendition wajib
  terkait versi video immutable. Parent wajib sesuai snapshot request job.
- Reuse validator FFmpeg daripada dependency image baru. PNG/JPEG saja merupakan
  batas dukungan yang disengaja, bukan fallback diam-diam.
- Repeat completion pada job terminal mengembalikan False, tidak overwrite/upsert.
  Dua publisher dengan lease sama menghasilkan tepat satu pemenang; file pihak
  kalah dibersihkan. Ini retry safety, bukan reuse UUID/file hasil percobaan lama.
- Commit outcome unknown mempertahankan file dan mencoba rekonsiliasi; snapshot
  kosong tidak dianggap bukti aman untuk menghapus file.
- Status/progress, lease/recovery policy, lifecycle client OpenAI, proposal
  acceptance, EditPlan dan renderer manual tidak diubah.

## G. Verifikasi aktual

Semua perintah menggunakan uv run; flag --tb=short membatasi diagnostic sensitif.
Test PostgreSQL memakai TEST_DATABASE_URL database bernama *_test, schema UUID
sementara. Tidak menggunakan development/production schema.

### Ruff final

```sh
uv run ruff check src/intentcut/backend/artifacts src/intentcut/backend/ai_artifacts.py src/intentcut/backend/ai_job_service.py src/intentcut/backend/ai_worker.py src/intentcut/backend/storage/database.py src/intentcut/backend/storage/database_models.py src/intentcut/backend/jobs/dispatch.py tests/unit/backend/test_derived_artifacts.py tests/unit/backend/test_job_dispatch.py tests/integration/backend/test_derived_artifacts.py
```

Hasil: All checks passed.

### Unit final

```sh
uv run pytest tests/unit/backend/test_derived_artifacts.py tests/unit/backend/test_job_dispatch.py tests/unit/backend/test_ai_artifacts.py tests/unit/backend/test_unit_ai_worker.py tests/unit/backend/test_unit_ai_job_api.py tests/unit/backend/test_worker_cli.py -q --tb=short --basetemp=/tmp/intentcut-batch2-unit-final
```

Hasil: 128 passed, 0 failed, 0 skipped (3.68 s).

### Regresi PostgreSQL/FFmpeg

```sh
uv run pytest tests/integration/backend/test_derived_artifacts.py tests/integration/backend/test_ai_artifact_repository.py tests/integration/backend/test_typed_worker_dispatch.py tests/integration/backend/test_ai_worker.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_manual_editing.py tests/integration/backend/test_revision_proposals.py -q --tb=short --basetemp=/tmp/intentcut-batch2-regression
```

Hasil: 130 passed, 0 failed, 0 skipped (48.18 s). Pada saat ini suite derived
berisi 28 kasus. Suite kemudian diperluas dengan dua kasus worker-failure dan
expiry setelah INSERT; regresi lain tidak diulang karena tidak berubah.

```sh
uv run pytest tests/integration/backend/test_derived_artifacts.py -q --tb=short --basetemp=/tmp/intentcut-batch2-derived-final
```

Hasil: 30 passed, 0 failed, 0 skipped (8.72 s). Ada overlap dengan eksekusi di atas;
jangan menjumlahkan 130+30 sebagai kasus unik. Total integrasi unik: 132 kasus.
Assertion test expiry setelah INSERT kemudian diperkuat untuk memastikan INSERT
benar-benar terjadi, dan kasus tersebut dijalankan ulang: 1 passed (1.48 s).

Evidence utama:

- Caption JSON fixture, PNG/JPEG hasil FFmpeg dan MP4 fixture lokal berhasil
  dipublikasikan, di-list, dan di-download melalui HTTP; byte dan MIME cocok.
- Malformed/oversized JSON, invalid/rusak/unsupported image, video invalid,
  durasi caption salah, symlink, hash/parent bytes salah, cross-project parent,
  wrong pipeline dan job-parent mismatch ditolak tanpa artifact authoritative.
- Image dimensi berlebih/multiframe/oversized ditolak sebelum decode lanjutan.
- Parent opsional image, parent wajib caption; worker derived nyata menjalankan
  fixture handler, bukan provider AI.
- Lease salah/expired/failed/lost, loss setelah file publication, competing
  publishers, recovery/reclaim token baru, dan expiry setelah INSERT teruji.
- Commit unknown setelah commit nyata direkonsiliasi; unknown tanpa bukti commit
  mempertahankan file tanpa mendaftarkan artifact parsial.
- Modifikasi workspace setelah sukses tidak mengubah output; korupsi file final
  terdeteksi pada snapshot; download lintas project mendapat 404.
- Migrasi pada bentuk tabel legacy diuji dua kali dan mempertahankan row ID/hash.
- First-cut, manual render/frame manifest, revision proposal, worker/client
  lifecycle dan legacy artifact publication lulus regresi relevan.

Saat mengembangkan test terdapat kegagalan setup (urutan argumen service dan
akses TestClient non-loopback/API disabled), lalu diperbaiki. Ruff awal juga
menemukan formatting/panjang baris; pemeriksaan final bersih. Tidak ada failure
akhir yang disembunyikan. Tidak ada browser test, paid inference, frontend build,
atau full backend suite di batch backend terfokus ini.

## H. Keamanan, reliability, dan batas tersisa

Artifact immutable melalui kontrak INSERT-only dan unique(job_id,kind), bukan
klaim filesystem WORM atau larangan DBA mengubah data. Path hanya dibuat server,
no-follow descriptor storage tetap dipakai. Hash parent/output dan snapshot
menahan perubahan byte yang tidak cocok. SQL fencing berlaku sebelum dan sesudah
INSERT; progress dibersihkan pada terminal/recovery sesuai mekanisme lama.

Project UUID bukan autentikasi user. Middleware local-only tetap menjadi batas
akses yang tersedia. Jangan mengekspos publik dengan menganggap project scoping
ini sudah setara auth produksi.

Crash setelah file publish sebelum commit, atau commit outcome unknown yang belum
terkonfirmasi, dapat meninggalkan orphan file privat. Itu disengaja untuk
menghindari penghapusan output yang mungkin sudah committed. Tidak ditambahkan
GC/reconciler daemon baru. Pemulihan diuji dengan expiry/reclaim dan exception
injection; belum dilakukan SIGKILL worker nyata, disk-full atau power-loss test.
FFmpeg memakai timeout yang ada, bukan sandbox OS/memory isolation baru.

Tidak ada live model validation, transcript sungguhan, AI-generated image,
caption burning atau efek video baru. Fixture MP4 membuktikan validasi/publikasi,
bukan membuktikan transformasi visual AI. Tidak ada UI derived artifact baru.

## I. Status migrasi dan rollout

004_derived_artifacts.sql disiapkan dan diuji hanya di schema test terisolasi.
BELUM diterapkan ke development atau production. Tidak restart API/worker.
Migrasi menambah content_type, parent_artifact_id, parent_sha256; parent FK dan
checks; memperluas kind. Tidak menambah tabel atau mengubah row lama.

Wajib review/backup, kemudian jalankan migrasi dalam transaksi menggunakan
mekanisme PostgreSQL yang kompatibel, sebelum menjalankan runtime dengan model
SQLAlchemy baru. Kode ORM baru memerlukan ketiga kolom tersebut: build ini tidak
siap di-rollout ke database lama sebelum migrasi disetujui/diterapkan. Runtime
existing tidak diverifikasi langsung dalam batch ini.

## J. Batch berikutnya (belum dikerjakan)

Batch 3 Muse Voice dapat mem-pin video parent ID/hash pada request job,
menambahkan admission/handler resmi setelah kontrak provider diverifikasi,
mengubah output provider menjadi CaptionDocument, lalu mengembalikan
CaptionArtifactResult. Caption hasil editing harus menjadi artifact/revisi baru;
video subtitle-burn memakai VideoRenditionResult dengan lineage versi video yang
tepat. Jangan otomatis mendaftarkan handler/menjalankan paid inference. Detail
provider, caption editing, subtitle escaping, admission dan UI menunggu persetujuan
Batch 3. Berhenti untuk review setelah laporan ini.
