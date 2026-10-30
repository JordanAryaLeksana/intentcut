# Integrasi Batch 4 + Batch 5

## Scope dan ancestry

Worktree terisolasi `/tmp/intentcut-integrate-b4-b5`, branch
`feat/integrate-captions-visuals`, dimulai dari Batch4
`da420b30959a0eac4ef5738f78767d329de630b1`.
Hanya Batch5 `020e07b957cf00f1ad926b04dad2449b392961c4` yang di-cherry-pick.
Baseline keduanya `1e92cfc4543c4cc67ed5862e5f4ee5cc45defaf2`.
Worktree fitur B4/B5 bersih sebelum integrasi; tidak diubah. Batch6 tidak disentuh.

Fetch origin menemukan master `091a9d396c6967d813e11d4e1b9772e728d28dc2` sudah
memuat Batch5 lewat PR3. Tree master sama persis dengan checkpoint Batch5.
Terhadap Batch4 sebelum integrasi: master 4 commit eksklusif, Batch4 1;
merge-base 1e92cfc. Lokal master tidak diubah. Tidak ada merge otomatis ke master.

## Resolusi konflik

Sebelas file berkonflik teks: worker CLI/worker, app, safe contracts, models,
Studio dock/store/CSS/workspace test, frontend API contracts dan progress parser.
Tiga file overlap lain auto-merge: dispatch, derived mapping, processing copy.

- CaptionSet dan ProjectCover serta index export tetap utuh.
- CAPTION_BURN menghasilkan VideoRenditionResult; IMAGE_GENERATE menghasilkan
  ImageArtifactResult. Legacy pair/storyboard publication tidak diubah.
- Router captions dan visuals sebelum route job UUID umum.
- Empat mode khusus mutually exclusive; captions-only tidak membuka Spark,
  Voice atau Image client. Image-only tidak mengeksekusi caption burn/Voice/Spark.
- Normal worker mempertahankan first-cut/manual/revision dan registrasi fitur
  sesuai konfigurasi. Processing loop tetap di dalam context OpenAI.
- Dock empat tab: Director, Inspector, Captions, Visuals; keyboard wrap/Home/End
  diperbarui. Dirty draft/history, native MP4 dan caption preview tetap dipertahankan.
- Selector video kecil dipakai Program Monitor dan Visuals. Captioned override
  memilih exact artifact ID dan job ID; metadata lama tidak menjadi fallback.
  Referensi current-video mengikuti rendition baru tanpa menyimpan artifact lama.

## File integrasi tambahan

| Path | Perubahan | Alasan |
|---|---|---|
| frontend/src/features/studio/monitor-video.ts | Added | Selector immutable video/rendition yang sama untuk Monitor dan Visuals |
| frontend/src/features/studio/program-monitor.tsx | Modified | Pin artifact pilihan pada job rendition |
| frontend/src/features/studio/visuals/visuals-panel.tsx | Modified | Ikuti captioned preview dan current-video reference |
| frontend/src/features/studio/__tests__/visuals.test.mjs | Modified | Regresi rendition, stale metadata, source reference |
| frontend/src/features/studio/__tests__/workspace-shell.test.mjs | Modified | Keempat tab/panel dan keyboard navigation |
| tests/unit/backend/test_worker_cli.py | Modified | Isolasi empat mode dan enam kombinasi yang dilarang |
| tests/integration/backend/test_captions_visuals_integration.py | Added | Migrasi bersama serta caption MP4 → image frame → cover/download |
| INTEGRATION_B4_B5.md | Added | Evidence dan batas integrasi |

Seluruh file Batch5 dari commit sumber ikut dipertahankan. Inventaris per fitur
berada di BATCH_4_EDITABLE_CAPTIONS.md dan BATCH_5_MUSE_IMAGE.md. Tidak ada dependency
baru dan tidak ada perubahan package/lockfile.

## Migrasi

Urutan 004 → 005 → 006 diuji dua kali pada schema disposable test_UUID, masing-masing
migrasi dalam transaksi. Test memulai dari bentuk pre004 dengan artifact legacy
video/storyboard yang sudah succeeded; UUID/checksum artifact dan status job
bertahan. Tabel caption_sets/project_covers dan index export tercipta dan rerun
idempotent. Schema fixture dibersihkan sesudah tes; development/production tidak
tersentuh. 005 dan006 independen satu sama lain; keduanya memakai kontrak004.
Approval migrasi dan backup tetap diperlukan sebelum runtime development baru.

## Perintah dan hasil aktual

Eksekusi Python memakai root `uv run --no-sync python`, PYTHONPATH menunjuk src
worktree integrasi, TEST_DATABASE_URL dibaca privat dan diverifikasi loopback serta
nama database berakhiran _test. Unit dan integrasi dijalankan dalam proses terpisah.

```sh
python -m pytest tests/unit/backend/test_caption_contracts.py tests/unit/backend/test_image_provider.py tests/unit/backend/test_voice_transcription.py tests/unit/backend/test_worker_cli.py tests/unit/backend/test_job_dispatch.py tests/unit/backend/test_unit_ai_worker.py tests/unit/backend/test_derived_artifacts.py tests/unit/backend/test_ai_artifacts.py tests/unit/backend/test_unit_ai_job_api.py -q --tb=short -p no:cacheprovider
python -m pytest tests/integration/backend/test_captions_visuals_integration.py tests/integration/backend/test_caption_editing.py tests/integration/backend/test_visual_assets.py tests/integration/backend/test_voice_transcription.py tests/integration/backend/test_typed_worker_dispatch.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_manual_editing.py tests/integration/backend/test_revision_proposals.py -q --tb=short -p no:cacheprovider
```

- Unit: **225 passed**, 0 failed/skipped, 4.37 detik.
- Integrasi: **106 passed**, 0 failed/skipped, 68.20 detik.
- Percobaan awal menggabungkan unit/integration dalam satu proses gagal collection
  (4 errors) karena basename test_voice_transcription identik; tidak ada model
  inference. Dipisah sesuai konvensi repository; hasil final di atas.
- Frontend: **99 case tests passed**, menjalankan setiap file langsung dengan
  `node --import tsx FILE`. Semua studio/__tests__/*.test.mjs, storyboard schema,
  modular API dan media selection ikut diuji.
- Ruff untuk Python berubah dan tes integrasi tambahan: passed.
- `npm run lint`: passed.
- `npm run build -- --webpack`: passed; compilation, TypeScript, static pages/traces.
- `./node_modules/.bin/tsc --noEmit --incremental false`: passed setelah build typegen.

Evidence FFmpeg nyata: subtitle glyph terlihat pada fixture, source immutable,
exact saved revision dirender, frame/audio validation dan full decode lulus.
Tes gabungan mengambil frame captioned MP4 yang sama, mengirim PNG frame ke provider
mock, menerbitkan image fixture dengan parent captioned ID/hash, menyimpan cover,
dan mengunduh MP4 serta PNG melalui API verified. Ini bukan bukti model live.

## Browser smoke terbatas

Frontend production terisolasi port3055, route /studio-preview tanpa project/API
runtime. Playwright memverifikasi 4 tab, click Captions → ArrowRight → Visuals pada
1440x900,1024x900,375x900. Tidak ada horizontal overflow; desktop tidak page-scroll,
mobile fallback vertikal. Screenshot direview:
`/tmp/intentcut-integrated-1440.png`, `/tmp/intentcut-integrated-1024.png`,
`/tmp/intentcut-integrated-375.png`. Screenshot laptop memperlihatkan clipping toolbar
pada state fokus keyboard; bukan bukti browser real-project penuh. Tidak merombak
layout existing di luar scope integrasi. Native playback/caption workflow browser
project nyata tetap belum diverifikasi karena schema development belum dimigrasi.

## Skills, security dan batas

Skill ui-ux-pro-max dari `.agents/skills/ui-ux-pro-max/SKILL.md` dibaca untuk dock,
keyboard dan viewport; guide Next use-client lokal juga dibaca. Tidak ada primitive
baru dipilih atau komponen shadcn dipasang. Tidak ada dependency baru.

Provider seluruhnya mock; paid inference tidak dijalankan. UUID project bukan auth.
Boundary lokal dan batas per-project bukan pengganti auth/spending ledger global.
Live Muse Voice/Image entitlement/protocol/quality tetap belum diverifikasi.
Tidak ada deployment, migrasi dev/prod, PR atau merge master. Hash final dan hasil
push/verifikasi merge-target dicatat dalam laporan akhir setelah commit.
