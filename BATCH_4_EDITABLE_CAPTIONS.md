# Batch 4 — Editable Captions dan Real MP4 Export

## A. Implementasi dan perilaku pengguna

Batch 4 menyediakan caption set persistent, text/enable editing, save dengan
optimistic concurrency, asynchronous subtitle export, serta preview/download
rendition di Studio. Sumber video dan transkripsi asli tidak dimodifikasi.
Transcribe Video memakai API Batch 3 yang nyata; selama pengembangan provider
hanya dimock dan tidak ada inference berbayar.

Checkpoint sebelum Batch 4 diverifikasi lokal dan melalui git ls-remote: branch
feat/m3-frontend menunjuk 1e92cfc4543c4cc67ed5862e5f4ee5cc45defaf2 di kedua sisi.
Laporan ini adalah catatan pra-commit Batch 4; hash/push akhirnya dilaporkan pada
respons engineering final, tanpa memasukkan hash self-referential ke dokumen.

## B. Arsitektur dan flow

1. Pilih video original AI, manual render, atau rendition di Program Monitor.
2. Captions panel mengambil state berdasarkan project + exact video artifact ID.
   Jobs/sets untuk video lain tidak dipakai. Query keys, mounted component keys,
   draft scopes dan stale-response guards memisahkan project/video/set.
3. Transcribe Video hanya mengirim request eksplisit ke Batch 3. Reload menemukan
   accepted job melalui server; tidak otomatis membuat request inference baru.
4. Sesudah transcript tersedia, Edit transcript membuat caption set idempotent.
   Original transcription tetap immutable artifact; set menyimpan FK/hash-nya.
5. Edit hanya mengubah text/enabled. Cue index, timestamp, count dan order berasal
   dari original transcript. Saved head memiliki persistent revision dan checksum
   video parent; stale save/export mendapat 409.
6. Export mengunci head, memeriksa expected_revision, lalu menyalin seluruh saved
   revision ke private job payload. Unique index membatasi satu job/set/revision.
7. caption_burn_v1 dirutekan ke CaptionBurnProcessor. Mode --captions-only tidak
   membuat Muse Spark atau Voice client. Tidak ada transaksi DB selama FFmpeg.
8. Worker memverifikasi parent snapshot dan memakai textfile UTF-8 + drawtext
   expansion=none. Teks tidak diinterpolasikan ke shell/filter expressions/ASS.
9. FFprobe memeriksa frame count/FPS/duration/audio; FFmpeg melakukan decode penuh.
   Publisher Batch 2 memverifikasi checksum, parent lineage, lease dan completion
   atomik sebelum artifact menjadi authoritative.
10. Output kind=rendition memiliki parent ID/hash dan caption set/revision yang
    dapat diambil dari artifact listing. Preview/download memakai existing verified
    blob/player. User harus memilih output sukses; edits belum mengubah MP4 lama.

Native caption preview memakai satu TextTrack per video element dan VTTCue dari
state editing. Markup di-escape, disabled cue tidak dimasukkan. Preview dilabeli
belum burned; revisi terbaru baru menjadi MP4 setelah export sukses. Native track
behavior di browser live belum diverifikasi karena runtime development belum
kompatibel dengan migrasi yang pending.

## C. Inventaris file lengkap

Tidak ada file dihapus. Seluruh perubahan berikut berada setelah checkpoint
sebelumnya dan merupakan scope Batch 4.

| Full relative path | Status | Responsibility / alasan |
|---|---|---|
| src/intentcut/backend/captions/__init__.py | Added | Namespace caption editing/export |
| src/intentcut/backend/captions/schemas.py | Added | Strict edit/snapshot contracts dan plain-text validation |
| src/intentcut/backend/captions/service.py | Added | Project-scoped create/get/save/export/recovery, 409 conflicts |
| src/intentcut/backend/captions/routes.py | Added | Caption APIs di local-only AI boundary |
| src/intentcut/backend/captions/processor.py | Added | Lease-aware saved-snapshot render, tanpa inference |
| src/intentcut/backend/captions/render.py | Added | Safe textfile renderer, frame/audio validation, layout limits |
| src/intentcut/backend/storage/database_models.py | Modified | CaptionSet dan unique export-revision index |
| scripts/migrations/005_caption_sets.sql | Added | Additive/idempotent caption persistence migration |
| src/intentcut/backend/jobs/dispatch.py | Modified | Explicit CAPTION_BURN → VideoRenditionResult |
| src/intentcut/backend/artifacts/derived.py | Modified | Expected rendition kind untuk caption_burn_v1 |
| src/intentcut/backend/ai_worker.py | Modified | Direct processor capability registration |
| src/intentcut/backend/worker_cli.py | Modified | Caption registration dan provider-free --captions-only |
| src/intentcut/backend/app.py | Modified | Router/service wiring |
| src/intentcut/backend/contracts.py | Modified | Safe unsupported-render error code |
| src/intentcut/backend/artifacts/schemas.py | Modified | Optional caption set/revision lineage |
| src/intentcut/backend/artifacts/routes.py | Modified | Expose only safe output lineage from producing job |
| frontend/src/lib/api/captions.ts | Added | Typed API validation, scoped requests, exact-ID guards |
| frontend/src/lib/api/contracts.ts | Modified | Voice stages dan optional artifact lineage |
| frontend/src/lib/api/job-progress.ts | Modified | Parse truthful Batch 3 progress stages |
| frontend/src/features/studio/captions/captions-panel.tsx | Added | Transcribe/edit/save/export/recovery/status dan accessible form |
| frontend/src/features/studio/captions/store.ts | Added | Project/video/set-scoped dirty drafts dan rendition selection |
| frontend/src/features/studio/captions/preview.ts | Added | Enabled cue projection dan native-preview text escaping |
| frontend/src/features/studio/studio-dock.tsx | Modified | Captions tab dan keyboard navigation untuk tiga tab |
| frontend/src/features/studio/store/use-draft-store.ts | Modified | Captions dock selection tanpa mengubah manual timeline history |
| frontend/src/features/studio/program-monitor.tsx | Modified | Preview rendition dan truthful version label |
| frontend/src/features/studio/draft-persistence.tsx | Modified | Switch original/manual/captioned preview; clear override pada manual render |
| frontend/src/features/studio/ai-director/video-artifact-player.tsx | Modified | Native TextTrack preview, generic rendition playback/download |
| frontend/src/features/studio/ai-director/processing-state.ts | Modified | Voice stages dan safe caption/Voice error descriptions |
| frontend/src/features/studio/studio.css | Modified | Dock caption forms/spacing/focus/mobile controls |
| frontend/src/features/studio/__tests__/captions.test.mjs | Added | API, stores, isolation, stale responses, form SSR, preview, polling |
| frontend/src/features/studio/__tests__/workspace-shell.test.mjs | Modified | Keyboard navigation regression untuk tiga tab |
| tests/unit/backend/test_caption_contracts.py | Added | Text, timestamps, disabled cue, revision dan layout guard |
| tests/unit/backend/test_worker_cli.py | Modified | New typed registration dan provider-free caption-only mode |
| tests/integration/backend/test_caption_editing.py | Added | PostgreSQL/FFmpeg/HTTP, pixel evidence, conflicts, recovery, migration |
| BATCH_4_SUBTITLE_RENDER_EVIDENCE.json | Added | Measured metadata/hash/pixel/audio evidence; bukan model output |
| BATCH_4_EDITABLE_CAPTIONS.md | Added | Engineering report dan rollout limitations |

Fixture MP4 dan frame PNG tersedia di .local/batch4-evidence/ yang di-ignore.
Binary, cache, .env, private footage dan database dumps tidak masuk checkpoint.

## D. APIs, models dan fungsi

API prefix: /projects/{project_id}/ai-jobs. Semua memakai access boundary lokal
existing; tidak menganggap UUID sebagai autentikasi user.

| Method/path sesudah prefix | Contract |
|---|---|
| GET /videos/{video_id}/captions | Matching sets, transcript references dan transcription/export jobs untuk exact parent/hash |
| POST /caption-sets | {transcription_artifact_id}; idempotent create dari immutable caption artifact |
| GET /caption-sets/{id} | Saved head beserta fixed source timing dan revision |
| PUT /caption-sets/{id} | {expected_revision,cues:[{index,text,enabled}]}; stale → 409 |
| POST /caption-sets/{id}/exports | {expected_revision}; async/idempotent same revision |

Status/download tetap GET /{job_id} dan GET /{job_id}/artifacts[/artifact_id].

CaptionSet table memiliki FK original transcription artifact, project, video parent;
parent/transcription SHA; revision; duration_ms; cues JSONB; updated_at. Original
artifact terpisah tetap immutable. Hanya current head mutable; tiap submitted
export menyimpan snapshot lengkap revisinya, sehingga perubahan sesudah admission
bukan perubahan input job. Tidak menambah revision-history table atau queue baru.

Fungsi inti:

- CueEdit/SavedCue: text/enabled strict dan source timing tervalidasi.
- validate_text/validate_saved_cues: tolak C0/bidi override, timestamp invalid dan
  ordering palsu. Disabled blank text valid dan tidak menjadi fake subtitle.
- CaptionService: authorized create/get/save, locked revision check dan immutable
  export snapshot. Hash/video lineage tidak diterima sebagai authority dari browser.
- CaptionBurnProcessor: memeriksa snapshot/parent identity, progress dan lease.
- burn_captions/frame_info: safe local subtitle composition + actual media checks.
- CaptionFields/CaptionEditor: pemisahan accessible form dari network/store hooks.
- captionScope/captionDirty/useCaptionStore: preserve typing during saves/refetch,
  explicit conflict reload, protect against late ACK/wrong-source response.
- videoCaptionsKey/captionPolling: scoped React Query, ~2-second active polling,
  terminal stop, focus recovery. No automatic paid mutation retries.

## E. Skills dan dependencies

Skill: ui-ux-pro-max.
Exact path: /home/jordan/Documents/Hackaton-Meta/intentcut/.agents/skills/ui-ux-pro-max/SKILL.md.
Dipakai untuk labelled forms, keyboard tabs, visible async/error feedback, responsive
controls dan client-component boundaries. Search UX dan Next.js stack dilakukan.
Root/frontend AGENTS.md serta local Next.js use-client guide juga diperiksa.

shadcn MCP discovery berhasil menemukan textarea primitive. Tidak menginstal
component/package; existing native controls dan styling tokens dipakai kembali.

Tidak ada dependency/package baru atau perubahan package manifests/lockfiles.
Memakai FFmpeg drawtext/libfreetype dan DejaVu Sans yang sudah tersedia. Font path
saat ini /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf; deployment tanpa font ini
akan gagal aman. Tidak menginstal font atau OS packages.

## F. Keputusan engineering dan tradeoffs

- Satu mutable head/table; original transcript immutable dan submitted job snapshot
  memberi reproducibility tanpa event framework/revision tables tambahan.
- Edit timestamp/reorder/delete cue tidak ditambahkan. Enabled=false adalah cara
  menghilangkan cue tanpa merusak source timing/identity.
- Drawtext textfile + expansion=none dipilih agar percent/backslash/brace/HTML-like
  text menjadi literal, bukan ASS override atau filter expression. Tidak memakai
  arbitrary user subtitle file, shell command, font path atau filter input.
- Reencode video H.264 CRF18/passthrough frame timing; audio stream copy. Validasi
  menolak perubahan frame count/FPS/duration/audio di luar toleransi yang ditentukan.
  Bukan klaim pixel-identical video setelah reencode atau frame-accurate word timing.
- Zero enabled cues membuat rendition byte-identical dengan source, dilabeli
  unchanged/no active cues, bukan subtitle yang seolah-olah ditambahkan.
- Safety budget renderer: maksimal 200 enabled cues, empat wrapped lines/cue,
  maksimal tiga overlapping lanes, dan layout harus muat pada frame. Kasus yang
  tidak muat ditolak processing_limit, tidak disembunyikan/truncated.
- UTF-8/Latin fixture terverifikasi; coverage font seluruh bahasa Muse belum diuji.
- Export same set/revision mengembalikan job sebelumnya, termasuk failed; tidak ada
  force-retry API. Recovery lease menggunakan bounded attempts existing. Setelah
  memperbaiki error, save revision baru atau review operator diperlukan.
- Source binding tidak dipindah saat memilih video lain. Captioned output adalah
  video version lain, bukan mutasi original/manual render.

## G. Tests dan evidence aktual

Semua PostgreSQL tests memakai schema UUID sementara pada database khusus *_test.
Tidak ada inference berbayar, runtime development, atau migration dev/prod.

### Backend

```sh
uv run pytest tests/unit/backend/test_caption_contracts.py tests/unit/backend/test_voice_transcription.py tests/unit/backend/test_worker_cli.py tests/unit/backend/test_job_dispatch.py tests/unit/backend/test_unit_ai_worker.py tests/unit/backend/test_derived_artifacts.py tests/unit/backend/test_ai_artifacts.py tests/unit/backend/test_unit_ai_job_api.py -q --tb=short --basetemp=/tmp/intentcut-batch4-unit-final
```

189 passed, 0 failed/skipped (3.95 s). Satu layout guard case kemudian ditambahkan;
file unit caption dijalankan ulang: 16 passed (0.03 s). Total unit unik: 190,
bukan 189+16; 15 case overlap.

```sh
uv run pytest tests/integration/backend/test_caption_editing.py tests/integration/backend/test_voice_transcription.py tests/integration/backend/test_derived_artifacts.py tests/integration/backend/test_typed_worker_dispatch.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_manual_editing.py tests/integration/backend/test_revision_proposals.py tests/integration/backend/test_ai_worker.py tests/integration/backend/test_ai_artifact_repository.py -q --tb=short --basetemp=/tmp/intentcut-batch4-regression
```

168 passed, 0 failed/skipped (68.72 s). Sesudah disabled-blank edge case diperkuat:

```sh
uv run pytest tests/integration/backend/test_caption_editing.py -q --tb=short --basetemp=/tmp/intentcut-batch4-caption-final
```

17 passed, 0 failed/skipped (10.49 s). Total integration unik: 169; 16 case overlap.
Sesudah layout guard, positive actual-render case juga dijalankan ulang terfokus.

Ruff final scope: captions package, worker/app/contracts, artifact schemas/routes,
dispatch, database models, caption tests, CLI tests. Hasil All checks passed.
Scoped git diff --check bersih.

### Frontend

```sh
./node_modules/.bin/tsx --test src/features/studio/__tests__/*.test.mjs src/features/studio/ai-director/storyboard/storyboard-schema.test.mjs src/lib/api/modular-api.test.mjs src/features/studio/media/selection.test.mjs
npm run lint
./node_modules/.bin/tsc --noEmit
```

88 passed, 0 failed/skipped (554.77 ms); ESLint exit 0; TypeScript exit 0.
Initial SSR test provider-context mismatch diperbaiki dengan presentational
CaptionFields dan existing store/API conventions. Ada kegagalan perintah awal
karena cwd dan sandbox IPC; corrected command berhasil, bukan dianggap passed.

Production build:

- npm run build: gagal di Turbopack karena binding port EPERM pada CSS worker.
- Satu fallback resmi local Next.js CLI: npm run build -- --webpack → exit 0,
  compiled, TypeScript, static generation dan build traces selesai; BUILD_ID ada.
- Tidak mengubah next.config atau package scripts untuk menyamarkan kegagalan.
  Default Turbopack tetap perlu verifikasi di environment yang mengizinkan IPC.

### Actual subtitle MP4

BATCH_4_SUBTITLE_RENDER_EVIDENCE.json mencatat fixture aktual:

- Source/output: H.264, AAC, 48 frames, 24/1 FPS, durasi video 2.000000 detik.
- SHA output berbeda dari source; source bytes tidak berubah.
- Decoded audio hash source/output sama.
- Pada 800 ms: source 0 white pixels, output 164 white pixels dari glyph subtitle.
- Pada 100 ms (sebelum cue): output 0 white pixels.
- Frame PNG diperiksa visual: teks FIRST REVISION terlihat di bagian bawah video.
- Export revision 2 tetap memakai FIRST REVISION meskipun saved head sudah revision
  3 SECOND REVISION; export berikutnya menghasilkan output/hash terpisah.

MP4/frame fixture lokal: .local/batch4-evidence/fixture-captioned.mp4 dan
captioned-0800ms.png. Transcription evidence sintetis; bukan klaim Muse live.

Tests juga mencakup save/reload/409 concurrent save, cross-project/source tamper,
fixed timestamps, empty/no-speech/disabled cue, literal filter syntax, renderer
failure tanpa partial artifact, stale lease/recovery, original immutability,
migration creation/idempotency/preservation, first-cut/manual/revision regression,
front-end video/project isolation, late save response guards, scoped APIs,
terminal polling dan live-preview text escaping.

## H. Security, migration dan limitations

Project UUID bukan user authentication. Existing local-only AI middleware dipakai
untuk seluruh caption routes. Request/body dan metadata yang dikembalikan di-allowlist;
private paths, credentials, provider diagnostics dan job snapshot tidak diekspos.
DB row locks + expected revision memagari save/export; publisher/worker memagari
lease, hash, atomic completion dan immutable result identity. No AI inference
untuk caption editing/export.

Migration 004 tetap pending di development. Migration 005_caption_sets.sql hanya
disiapkan dan diuji pada schema test terisolasi; tidak diterapkan ke dev/prod.
Urutan rollout: approval eksplisit → stop API/worker → verified private backup →
004 dalam transaksi → 005 dalam transaksi → schema checks → restart. Jangan memakai
create_all sebagai pengganti migration. Backup/restart procedure sebelumnya berada
di BATCH_3_MUSE_VOICE_BACKEND.md bagian I. Kode ORM baru tidak boleh dijalankan pada
schema development lama.

Worker lokal untuk rendering setelah schema kompatibel:
uv run intentcut-ai-worker --captions-only --max-jobs 1 --max-attempts 2
Gunakan --job-id bila hanya satu accepted export yang diizinkan. Jangan menjalankan
Voice worker tanpa paid-inference approval terpisah.

Playwright desktop/mobile smoke tidak dijalankan: development runtime belum
kompatibel karena 004/005 belum applied. Tidak membuat fake production data atau
menjalankan runtime tidak kompatibel untuk mendapatkan screenshot. UI responsive
styles dan SSR/automated tests lulus; native track behavior, actual browser
playback/download, mobile layout, dan live caption workflow tetap perlu satu
focused smoke setelah migration approval. Video decode/frame evidence terverifikasi
secara lokal, bukan browser evidence.

Tidak ada arbitrary trims, timing editing, subtitle style editor, SRT upload,
font picker, per-word timing, advanced effects atau live Muse verification.
Font availability/coverage, default Turbopack build environment, force retry failed
export dan real crash/disk-full behavior merupakan batas yang masih tersisa.

## I. Git checkpoint

Sebelum commit: required test/build results di atas diverifikasi, scope Batch 4
akan diaudit dan staged content discan untuk exact local secrets/pattern, binary,
backup/cache dan whitespace. Generated MP4/PNG tetap ignored. Commit/push hanya
feature branch existing, tidak force/merge. Hash final dan remote verification
akan disampaikan pada completion report.

## J. Rekomendasi Batch 5 (belum dimulai)

Muse Image vertical slice: verifikasi official model/request/response dan akses;
explicit paid admission; authorized frame extraction; one thumbnail/cover request
melalui typed worker; image byte/dimension validation dan immutable provenance;
Studio review/preview/download. Pertahankan cover-only asset terpisah dari title
card yang benar-benar masuk MP4. Defer title-card composition/editing sampai
thumbnail slice dan runtime/migration/live verification siap. Jangan mulai Batch 5
otomatis atau memanggil provider tanpa approval terpisah.
