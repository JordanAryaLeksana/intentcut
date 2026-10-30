# Batch 3 — Muse Voice Transcription Backend

## A. Ringkasan

Backend transkripsi sekarang terhubung ke kontrak resmi Meta melalui adapter
HTTPS nyata yang tidak melakukan retry atau mengikuti redirect. Flow tersedia:
video artifact terverifikasi → job PostgreSQL → WAV full timeline → Muse Voice
ENDPOINTING → CaptionDocument tervalidasi → immutable caption artifact → verified
HTTP retrieval. Seluruh verifikasi menggunakan provider mock, bukan inference
berbayar. Akses model akun dan kualitas transkripsi ucapan nyata belum diuji.

Tidak ada UI caption, editing caption, subtitle burning, Muse Image, SAM, atau
Batch 4. Tidak ada package baru, migrasi yang dijalankan di development/production,
restart runtime, perubahan .env, reset, commit, atau push.

## B. Audit, kontrak resmi, dan data flow sebelum/sesudah

Sebelumnya Batch 2 menyediakan result/artifact derived, tetapi belum ada adapter
Voice, extraction audio, admission transkripsi, atau handler worker transkripsi.
Jalur first-cut dan revision menggunakan Muse Spark; manual render tanpa inference.

Sekarang:

1. POST admission memeriksa feature flag/key, project-scoped successful video atau
   rendition artifact, snapshot size/hash, FFprobe duration dan batas aplikasi.
2. Job menyimpan pipeline_version, parent_artifact_id dan parent_sha256 dari server.
   Browser tidak mengirim path, URL, atau hash authoritative.
3. Project row lock menserialisasi admission; request UUID idempotent dan source
   artifact/hash yang sama menggunakan job sebelumnya, termasuk job gagal.
4. Worker bertipe hanya mengeksekusi caption_transcribe_v1. Heartbeat/recovery tetap
   memakai infrastruktur yang sama.
5. Input dibaca melalui verified private snapshot dan staging; FFmpeg membuat
   WAV mono signed 16-bit little-endian PCM 24 kHz sepanjang timeline video.
6. Offset dinormalisasi terhadap origin VIDEO. Audio yang mulai terlambat tetap
   didahului silence; gap/tail dipertahankan/padded. Tidak ada silence removal atau
   pemindahan ucapan ke waktu nol.
7. PCM seluruhnya nol atau video tanpa audio menghasilkan cues kosong tanpa
   inference. Ini bukan general VAD dan bukan klaim telah mendeteksi semua silence.
8. Untuk audio nonzero, worker melakukan COMMIT marker sebelum HTTP. Adapter
   mengirim satu request; hanya final turn data yang diproyeksikan ke caption.
9. Caption tervalidasi disimpan sebagai cache di private job payload dengan lease
   fencing. Raw provider response/diagnostic tidak dipersist atau diekspos.
10. Publisher Batch 2 memverifikasi parent, output, checksum dan lease; registrasi
    artifact dan status succeeded atomik. Download memakai verified snapshot.

### Sumber resmi yang diperiksa

- https://dev.meta.ai/docs/speech-to-text
- https://dev.meta.ai/docs/api-reference/voice/transcribe
- https://dev.meta.ai/docs/api-reference/voice/schemas
- https://dev.meta.ai/docs/models

Model: muse-voice-transcribe-1.0. Endpoint tetap:
POST https://api.meta.ai/v1/asr/transcribe?sessionId=<job-UUID>.
Bearer authentication di HTTP header; Accept: application/json.

Multipart terdiri dari:

```text
request (application/json):
{"model":"muse-voice-transcribe-1.0","audioEncoding":"WAV","mode":"ENDPOINTING"}
audio (audio/wav): bytes WAV; filename audio.wav
```

Buffered response resmi memiliki sessionId, transcript, audioDurationMs dan turns.
Turn memiliki turnId, startMs, endMs, transcript, speaker opsional. Boundary turn
merupakan waktu audio yang telah diproses saat onset/end terdeteksi; bukan batas
akustik presisi atau word-level timestamp. Tidak dibuat word timing baru.
ENDPOINTING tidak meminta diarization; speaker label tidak diada-adakan.

Batas provider: audio maksimal 10 menit, request body maksimal 32 MB, WAV mono
16-bit PCM 16/24 kHz. Aplikasi memilih 24 kHz dan batas body konservatif 32.000.000
byte termasuk multipart. Batas default produk 120 detik; konfigurasi hanya boleh
maksimal 600 detik. WAV PCM maksimal 600×24.000 frame ditambah header bounded.

Dokumentasi resmi terverifikasi; endpoint berbayar tidak dipanggil. Entitlement
API key, respons live aktual dan kualitas recognition tetap memerlukan live test.

## C. Inventaris file

Status relatif terhadap awal Batch 3. File yang sudah untracked/modified dari
batch sebelumnya tetap dipertahankan; tidak ada file dihapus.

| Full relative path | Status | Responsibility dan alasan |
|---|---|---|
| src/intentcut/ai/voice.py | Added | Adapter HTTPS/multipart resmi, parser final turns, validasi WAV/response bounded |
| src/intentcut/backend/transcription/__init__.py | Added | Namespace backend transkripsi |
| src/intentcut/backend/transcription/media.py | Added | Verified parent video dan extraction WAV full timeline |
| src/intentcut/backend/transcription/repository.py | Added | Marker provider-call dan caption cache persistent dengan fencing/uncertain commit |
| src/intentcut/backend/transcription/service.py | Added | Admission typed, idempotency, dedupe, project budget/pending limit |
| src/intentcut/backend/transcription/processor.py | Added | Orkestrasi worker tanpa Spark, silence/cache/recovery handling |
| src/intentcut/backend/transcription/routes.py | Added | POST transkripsi; menggunakan GET status/artifact existing |
| src/intentcut/backend/app.py | Modified | Wiring router/service transkripsi |
| src/intentcut/backend/ai_worker.py | Modified | Auto-wrap direct TranscriptionProcessor ke dispatcher bertipe |
| src/intentcut/backend/worker_cli.py | Modified | Registrasi Voice opt-in dan mode --voice-only tanpa client Spark |
| src/intentcut/backend/contracts.py | Modified | Safe public error codes transkripsi |
| src/intentcut/backend/artifacts/derived.py | Modified | Mapping caption_transcribe_v1 ke captions; kontrak Batch 2 tetap |
| src/intentcut/backend/jobs/dispatch.py | Modified | JobType.CAPTION_TRANSCRIBE dan result type eksplisit |
| src/intentcut/backend/jobs/progress.py | Modified | Stage nyata extracting_audio/transcribing_audio/validating_transcript |
| src/intentcut/backend/shared/settings.py | Modified | Feature opt-in, duration, job budget, timeout settings |
| tests/unit/backend/test_voice_transcription.py | Added | Protokol multipart, parsing, invalid output, WAV/provider bounds/errors |
| tests/unit/backend/test_worker_cli.py | Modified | Voice-only, mutually exclusive modes, konfigurasi dan lifecycle regresi |
| tests/integration/backend/test_voice_transcription.py | Added | PostgreSQL/FFmpeg/API, offset audio, lineage, cache/cost/fencing/recovery |
| BATCH_3_MUSE_VOICE_BACKEND.md | Added | Laporan, kontrak, evidence, instruksi operator dan batas implementasi |

## D. Classes, contracts, dan fungsi utama

- VoiceTurn / VoiceResponse: strict typed fields sesuai buffered protocol. Unknown
  provider fields tidak dipublikasikan. Turn ID int32 harus unik/ascending sesuai
  kontrak; tidak diperlakukan sebagai scene ID atau identitas speaker.
- parse_transcript: memeriksa duration (toleransi 50 ms), range turn, urutan cue,
  aggregate-vs-turn text, ukuran caption. Turn unfinished dengan text kosong tidak
  menjadi fake cue. Text tanpa usable timed turns ditolak.
- inspect_wav: memeriksa mono/16-bit/24k, durasi, ukuran, complete PCM payload dan
  exact-zero silence. WAV rusak atau di luar limit ditolak sebelum HTTP.
- MuseVoiceClient: HTTPSConnection stdlib ke host tetap, multipart resmi, bounded
  JSON response 1 MiB, timeout, close response/connection pada sukses maupun gagal.
- verified_video: mengambil artifact melalui project + succeeded job, menyalin
  snapshot terverifikasi ke staging dan melakukan FFprobe di luar transaksi DB.
- extract_audio: FFmpeg dengan copyts, origin video, resample/fill, pad dan batas
  sample akhir berdasarkan durasi video. Tidak memotong silence untuk biaya.
- TranscriptionRequest: hanya request_id dan artifact_id UUID; extra fields ditolak.
- TranscriptionService.submit: admission, request conflict, immutable-source dedupe,
  satu pending/running job per project dan batas jumlah job lifetime project.
- reserve_provider_call: fenced durable marker sebelum HTTP, maksimal satu izin
  provider-call per job. COMMIT exception dianggap uncertain.
- cache_caption: fenced persistence hanya CaptionDocument, bukan raw response.
- TranscriptionProcessor: orchestration, progress aktual, cache reuse, fail closed
  terhadap reserved-but-uncached attempt dan jalur CaptionArtifactResult.
- TranscriptionAccepted: id/status/created_at/status_url/artifacts_url yang aman.
  Reused job dapat sudah succeeded/failed; response tidak memalsukan queued.

### Public API

```http
POST /projects/{project_id}/ai-jobs/transcriptions
Content-Type: application/json

{"request_id":"<UUID unik>","artifact_id":"<UUID video/rendition>"}
```

Respons 202 berisi id, status aktual, created_at, status_url dan artifacts_url.
Location menunjuk status_url. URL status tetap:
GET /projects/{project_id}/ai-jobs/{job_id}.

Artifact retrieval tetap:
GET /projects/{project_id}/ai-jobs/{job_id}/artifacts dan download_url dari item.
Output tunggal kind=captions, MIME application/json, parent ID/hash persis sesuai
source. Caption JSON memakai schema captions-v1 Batch 2 dengan duration_ms/cues.
Tidak ada storyboard palsu atau perubahan artifact AI/manual yang sudah terbit.

Safe error tambahan: invalid_transcript, transcription_outcome_unknown,
transcription_rate_limited; provider_unavailable/source_unavailable/processing_limit
memakai mekanisme yang sudah ada. Admission memakai code terpisah seperti
transcription_unavailable, transcription_pending, transcription_limit,
request_conflict dan not_found. Tidak ada private request payload/lease/raw
response/key/path di GET job maupun artifact listing.

## E. Skills dan dependencies

AGENTS.md root dan katalog skills telah diperiksa; tidak ada AGENTS tambahan di
src/tests/scripts. Tidak menggunakan skill karena katalog tersedia berfokus pada
UI, OpenAI-specific docs, skill management atau plugin yang tidak membantu
implementasi backend Meta ASR ini. Tidak ada path SKILL.md yang diterapkan.

Tidak ada package ditambah/dihapus/diinstall. pyproject.toml dan uv.lock tidak
berubah. Memakai Python stdlib http.client, wave, json serta Pydantic, SQLAlchemy,
PostgreSQL dan FFmpeg/FFprobe yang sudah ada. OpenAI SDK tidak dipaksakan untuk
endpoint ASR yang mempunyai multipart/protokol tersendiri.

## F. Tradeoff dan alternatif yang ditolak

- Tidak menambah queue, table atau generic multimodal framework. Job payload JSONB
  yang sudah private cukup untuk marker/cache caption terbatas ukuran.
- HTTP blocking hanya terjadi di worker, tidak di FastAPI admission. Tidak ada DB
  transaction terbuka selama inference/FFmpeg. Connection dibuat/ditutup per call.
- sessionId hanya correlation handle, bukan klaim idempotency provider. Dedupe
  biaya dilakukan server IntentCut sendiri, bukan asumsi dedupe Meta.
- At-most-once paid-call admission dipilih daripada automatic retry jaringan.
  Jika worker crash setelah marker tetapi sebelum HTTP, satu job dapat gagal
  konservatif meskipun belum dibayar; ini lebih aman daripada membayar dua kali.
- Cached validated caption memungkinkan retry publication setelah crash/unknown
  completion tanpa mengirim audio lagi. Jika sudah reserved tetapi tidak ada
  cache, job gagal transcription_outcome_unknown.
- UUID request baru untuk source yang sama mengembalikan job lama, termasuk failed.
  Tidak ada public force-retry yang bisa melewati cost guard. Outage/429 memerlukan
  review operator; fitur retry eksplisit bukan bagian batch ini.
- Batas default: 120 detik/job, 3 admitted transcription jobs/project, satu aktif.
  Ini admission budget, bukan ledger mata uang global. Empty/no-audio jobs juga
  memakai slot. Project creation/auth/global credit management tidak diperluas.
- Speaker optional hanya dipertahankan bila provider benar-benar memberikannya;
  mode tetap ENDPOINTING. Tidak ada streaming, word timing, caption editing/burn.

## G. Verifikasi aktual

### Ruff final

```sh
uv run ruff check src/intentcut/ai/voice.py src/intentcut/backend/transcription src/intentcut/backend/ai_worker.py src/intentcut/backend/worker_cli.py src/intentcut/backend/app.py src/intentcut/backend/contracts.py src/intentcut/backend/jobs/dispatch.py src/intentcut/backend/jobs/progress.py src/intentcut/backend/shared/settings.py src/intentcut/backend/artifacts/derived.py tests/unit/backend/test_voice_transcription.py tests/unit/backend/test_worker_cli.py tests/integration/backend/test_voice_transcription.py
```

Hasil: All checks passed. Scoped git diff --check juga bersih. Tidak ada perubahan
pyproject.toml/uv.lock. Ruff awal menemukan formatting/panjang baris yang kemudian
diperbaiki; tidak ada lint failure tersisa.

### Unit regression final

```sh
uv run pytest tests/unit/backend/test_voice_transcription.py tests/unit/backend/test_worker_cli.py tests/unit/backend/test_job_dispatch.py tests/unit/backend/test_unit_ai_worker.py tests/unit/backend/test_derived_artifacts.py tests/unit/backend/test_ai_artifacts.py tests/unit/backend/test_unit_ai_job_api.py -q --tb=short --basetemp=/tmp/intentcut-batch3-unit-final
```

Hasil: 173 passed, 0 failed, 0 skipped (3.85 detik).

### PostgreSQL/FFmpeg regression final

```sh
uv run pytest tests/integration/backend/test_voice_transcription.py tests/integration/backend/test_derived_artifacts.py tests/integration/backend/test_typed_worker_dispatch.py tests/integration/backend/test_uploaded_job_flow.py tests/integration/backend/test_manual_editing.py tests/integration/backend/test_revision_proposals.py tests/integration/backend/test_ai_worker.py tests/integration/backend/test_ai_artifact_repository.py -q --tb=short --basetemp=/tmp/intentcut-batch3-integration-final
```

Hasil: 151 passed, 0 failed, 0 skipped (57.74 detik).

Satu kasus ACK-loss reservasi kemudian ditambahkan dan dijalankan terfokus:

```sh
uv run pytest tests/integration/backend/test_voice_transcription.py::test_reservation_commit_ack_loss_prevents_http_and_automatic_retry -q --tb=short --basetemp=/tmp/intentcut-batch3-reservation-final
```

Hasil: 1 passed, 0 failed, 0 skipped (0.72 detik). Total integrasi unik: 152.
Suite lain tidak diulang setelah penambahan test-only ini.

Evidence acceptance:

- MP4 fixture nyata dua detik dengan audio mulai sekitar 0,5 detik menghasilkan
  WAV mono s16/24k persis 48.000 sampel; 350 ms awal dan 250 ms akhir tetap nol,
  signal tone pada posisi tengah tetap ada. Bukan klaim source mengandung ucapan.
- Multipart diperiksa dengan MIME parser: part request JSON/model/mode/encoding
  tepat, part audio byte-identical dengan WAV, header auth/Accept dan URL tepat.
- Turn parsing valid/empty/unfinished, timestamps invalid, inconsistent transcript,
  malformed/oversized/wrong-content-type response ditangani.
- No-audio/digital silence tidak memanggil provider. Nonzero audio dengan mocked
  no-speech result menghasilkan cues kosong secara jujur.
- HTTP 301/400/401/429/500, timeout dan malformed JSON tidak di-retry otomatis;
  connection/response selalu ditutup. Source terlalu lama/besar ditolak.
- Wrong-project/non-video/tampered parent ditolak sebelum admission. Parent ID/hash
  dipersist oleh server dan cocok dengan caption download.
- Admission concurrent/idempotent, request conflict, pending limit dan project
  budget diuji pada PostgreSQL sebenarnya.
- Callback provider mock melihat marker committed melalui koneksi lain dan dapat
  heartbeat: tidak ada transaction lock tertahan selama inference.
- Crash sebelum reservation boleh pulih dan mengirim satu call. Crash setelah
  reservation tidak mengirim ulang. Cached response dipakai saat recovery.
- Lease hilang selama inference tidak bisa cache/publish; worker baru tidak call
  lagi. Uncertain artifact completion menggunakan cache saat retry publication.
- Reservasi benar-benar COMMIT lalu exception ACK diinjeksikan: HTTP tidak dikirim,
  marker tetap tersimpan, dan recovery juga tidak memanggil provider.
- First-cut/manual-render/revision/publication/client-lifecycle tetap lulus regresi.

Seluruh PostgreSQL test memakai database *_test dan schema UUID sementara.
Migrations dalam suite hanya menguji schema terisolasi. Tidak ada paid inference,
browser test, frontend build, SIGKILL/disk-full/power-loss test atau live runtime
smoke. Schema dan HTTP provider contract terverifikasi; model output nyata belum.

## H. Security, lifecycle, cost safeguards, dan limitations

- Project scope diperiksa melalui producing job; UUID project bukan autentikasi
  user. Middleware opt-in local-only tetap berlaku pada route ai-jobs baru.
- Jangan mengekspos publik atau percaya forwarded loopback sebagai user identity.
- Parent selalu canonical server storage; no public path/URL dan tidak ada SSRF.
- Lease token + running + clock expiry memagari marker, cache, progress, publication.
  Transaksi completion memeriksa expiry setelah artifact INSERT juga.
- Paid HTTP dilakukan sesudah reservation durable. Tidak ada automatic retry,
  redirect, Spark inference, video understanding atau footage reupload selain WAV.
- Voice-only tidak membuat client Spark. Normal Spark worker loop tetap di dalam
  OpenAI client context. Manual-only tidak membuat provider client.
- Validated caption cache persistent melindungi recovery/publication; raw provider
  payload tidak menjadi public evidence. Safe error codes tidak memuat diagnostics.
- Orphan file setelah crash/unknown commit tetap mungkin sesuai Batch 2; tidak
  menambahkan GC daemon. Tidak ada exactly-once guarantee eksternal: tradeoff ini
  at-most-once admission yang konservatif, dengan kemungkinan request tidak terkirim.
- Budget per-project tidak mencegah pengguna lokal membuat project baru. Tidak ada
  global currency ledger atau auth operator/reviewer baru; tetap private demo.
- Live model access, actual speech quality, real timeout/rate-limits dan end-to-end
  development runtime belum diuji. Tidak ada forced retry terhadap failed source.

## I. Migration 004 status dan deployment prerequisites

Inspeksi READ-ONLY memakai DATABASE_URL efektif, hanya bila target loopback dan
nama database intentcut. Pemeriksaan kedua menggunakan pg_attribute pada tabel
ai_job_artifacts yang benar-benar di-resolve PostgreSQL, bukan asumsi schema.

Hasil kedua inspeksi: content_type, parent_artifact_id, parent_sha256 semuanya
BELUM ADA pada database development. Migrasi 004 belum diterapkan. Tidak ada
migrasi baru Batch 3; marker/cache memakai request_payload yang sudah tersedia.
Tidak menjalankan ulang development API/worker terhadap schema yang tidak cocok.

### Instruksi aman migrasi — HANYA setelah approval eksplisit operator

1. Hentikan development API dan seluruh worker pada terminal/service pengelolanya.
2. Pastikan migrasi 001–003 sebelumnya sudah tersedia. Jangan memakai create_all /
   intentcut-init-db sebagai pengganti ALTER migration 004.
3. Sediakan pg_dump dan pg_restore yang kompatibel dengan versi PostgreSQL server.
4. Dari root repository, jalankan snippet berikut hanya sesudah migrasi disetujui.
   Script memverifikasi local target, membuat private custom backup, menguji daftar
   backup, lalu menjalankan migration 004 dalam satu transaksi. Kredensial tidak
   menjadi argumen proses atau output. Snippet ini BELUM dieksekusi oleh Codex.

```sh
uv run python - <<'PY'
import ipaddress
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from intentcut.backend.shared.settings import BackendSettings

os.umask(0o077)
settings = BackendSettings()
value = settings.database_url.get_secret_value()
url = make_url(value)
local = url.host == 'localhost'
try:
    local = local or ipaddress.ip_address(url.host or '').is_loopback
except ValueError:
    pass
if not local or url.database != 'intentcut':
    raise SystemExit('STOP: target bukan database development intentcut lokal')

root = Path('.local/backups')
root.mkdir(mode=0o700, parents=True, exist_ok=True)
backup = root / ('intentcut-before-004-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.dump')
pg_env = dict(os.environ, PGHOST=url.host, PGPORT=str(url.port or 5432),
              PGDATABASE=url.database, PGUSER=url.username or '',
              PGPASSWORD=url.password or '')
try:
    subprocess.run(['pg_dump', '--format=custom', '--no-owner', '--file', str(backup)],
                   env=pg_env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    subprocess.run(['pg_restore', '--list', str(backup)], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
except (OSError, subprocess.CalledProcessError):
    raise SystemExit('STOP: backup gagal/belum dapat diverifikasi; migrasi tidak dijalankan')

engine = create_engine(value, connect_args={'connect_timeout': 5})
try:
    with engine.begin() as connection:
        before = connection.execute(text('SELECT count(*) FROM ai_jobs')).scalar_one()
        artifact_count = connection.execute(text('SELECT count(*) FROM ai_job_artifacts')).scalar_one()
        connection.execute(text(Path('scripts/migrations/004_derived_artifacts.sql').read_text()))
        columns = set(connection.execute(text("SELECT attname FROM pg_attribute WHERE attrelid=to_regclass('ai_job_artifacts') AND attnum>0 AND NOT attisdropped")).scalars())
        assert {'content_type', 'parent_artifact_id', 'parent_sha256'} <= columns
        assert connection.execute(text('SELECT count(*) FROM ai_jobs')).scalar_one() == before
        assert connection.execute(text('SELECT count(*) FROM ai_job_artifacts')).scalar_one() == artifact_count
except Exception:
    raise SystemExit('STOP: transaksi migrasi gagal; jangan restart runtime')
finally:
    engine.dispose()
print('Backup terverifikasi; migrasi 004 committed; jumlah job/artifact tetap')
PY
```

Backup suitability di atas berarti pg_dump berhasil dan archive dapat dibaca;
restore drill lengkap tetap praktik operator yang belum diuji di development.
Migrasi idempotent/preservation sudah diuji di schema terisolasi, tidak diulang
berkali-kali pada database development.

### Restart sesudah migrasi berhasil

Untuk API saja, tanpa menyalakan inference secara otomatis:

```sh
uv run uvicorn intentcut.backend.app:create_app --factory --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Tetap VOICE_TRANSCRIPTION_ENABLED=false sampai test berbayar disetujui. Jalankan
kembali manual/Spark worker sesuai mode/budget sebelumnya hanya setelah memeriksa
queue; worker dapat memproses job queued yang nyata. Worker Spark tetap di dalam
client context. Untuk Voice, ikuti prosedur controlled test berikut.

## J. Satu controlled paid test — instruksi, BELUM dieksekusi

Prasyarat: approval terpisah untuk satu call Voice; migration 004 applied; API key
Meta punya akses muse-voice-transcribe-1.0; video rendered pendek berisi ucapan
nyata dan dimiliki project lokal; operator memeriksa queue dan tidak menjalankan
worker Voice continuous. Gunakan video yang belum pernah diminta transkripsi,
karena immutable-source dedupe akan mengembalikan job lama.

1. Restart API dengan MODEL_API_KEY di environment privat dan
   AI_JOBS_LOCAL_ENABLED=true, VOICE_TRANSCRIPTION_ENABLED=true.
   Untuk sesi test konservatif, VOICE_MAX_DURATION_SECONDS=30,
   VOICE_MAX_JOBS_PER_PROJECT=1. Jangan memasukkan key ke curl/history/log.
2. Dapatkan artifact_id video dari GET artifact listing yang sudah ada. Periksa
   project dan video preview; simpan ID project/video, bukan filesystem path.
3. Buat UUID request sekali. Submit sekali:

```sh
curl --fail-with-body -sS -X POST \
  "http://127.0.0.1:8000/projects/<PROJECT_UUID>/ai-jobs/transcriptions" \
  -H 'Content-Type: application/json' \
  --data '{"request_id":"<REQUEST_UUID>","artifact_id":"<VIDEO_ARTIFACT_UUID>"}'
```

4. Salin job id dari response, lalu jalankan worker bertarget tepat satu job:

```sh
VOICE_TRANSCRIPTION_ENABLED=true VOICE_MAX_DURATION_SECONDS=30 \
uv run intentcut-ai-worker --voice-only --job-id <JOB_UUID> --max-jobs 1 --max-attempts 1
```

Worker tidak membuat Muse Spark client. Tidak memakai --continuous. Flag duration
API dan worker harus konsisten. Secret MODEL_API_KEY dimuat privat, tidak ditulis
pada command. Audio tanpa stream/digital zero tidak menghasilkan paid call.

5. GET status_url hingga terminal, lalu artifacts_url. Download caption JSON lewat
   download_url. Pastikan kind=captions, parent ID/hash cocok, duration benar,
   text/timing sesuai ucapan dan silence tetap berada pada posisi aslinya.
6. Submit ulang request/source yang sama untuk mengonfirmasi job id tetap sama;
   jangan membuat source baru untuk melewati guard. Periksa usage dashboard Meta
   secara manual untuk satu call; jangan menganggap sessionId sebagai dedupe key.
7. Jika timeout/failed/unknown, STOP dan review operator. Jangan auto-retry atau
   reset marker di database. Matikan feature flag dan hentikan worker setelah test.

Kriteria lulus live: satu source ucapan nyata → satu provider call yang disetujui →
caption artifact immutable dengan lineage dan turn timing yang dapat diperiksa.
Belum ada klaim acceptance live ini lulus.

## K. Batch 4 — belum dimulai

Batch 4 perlu caption draft/revision persistence dengan optimistic conflicts,
editable text/timing yang tervalidasi, UI review, dan pengaitan ke video artifact
ID/hash yang tepat. Source rerender baru harus menandai caption lama sebagai stale;
jangan memindahkan caption diam-diam ke versi MP4 lain.

Subtitle export harus memakai saved caption revision, escaping text ASS/SRT yang
aman, worker async tanpa inference tambahan, FFmpeg subtitle burn yang nyata,
VideoRenditionResult dan lineage lengkap. Verifikasi stream/durasi/frame output,
preview/download versi yang benar, silence, multiline/Unicode dan failure recovery.
Tidak ada implementasi Batch 4 atau subtitle burning dalam batch ini. STOP review.
