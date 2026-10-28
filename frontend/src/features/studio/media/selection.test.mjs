import test from 'node:test';
import assert from 'node:assert/strict';
import { selectVideos, MAX_FILE_BYTES, formatBytes } from './selection.ts';
const video = (name = 'sample.mp4', type = 'video/mp4') => new File(['video fixture'], name, { type, lastModified: 1 });
test('multiple selections retain original File objects and existing selections', () => {
  const a = video(), b = video('second.webm', 'video/webm');
  const result = selectVideos([a], [b]);
  assert.deepEqual(result.files, [a, b]); assert.equal(result.added, 1); assert.deepEqual(result.errors, []);
});
test('invalid and empty files are rejected while valid files survive mixed batches', () => {
  const result = selectVideos([], [video('note.txt', 'text/plain'), new File([], 'empty.mp4'), video()]);
  assert.equal(result.files.length, 1); assert.equal(result.errors.length, 2);
});
test('duplicate selections are rejected within and across batches', () => {
  const a = video(); assert.equal(selectVideos([], [a, a]).files.length, 1);
  assert.equal(selectVideos([a], [video()]).errors.length, 1);
});
test('file count and per-file size limits are enforced', () => {
  const incoming = Array.from({length: 21}, (_, i) => video(`${i}.mp4`));
  assert.equal(selectVideos([], incoming).files.length, 20);
  const big = video(); Object.defineProperty(big, 'size', {value: MAX_FILE_BYTES + 1});
  assert.match(selectVideos([], [big]).errors[0], /exceeds 2 GiB/);
});
test('empty MIME uses supported extension; conflicting MIME is rejected', () => {
  assert.equal(selectVideos([], [video('clip.MP4', '')]).added, 1);
  assert.equal(selectVideos([], [video('clip.mp4', 'text/plain')]).added, 0);
});
test('sizes use readable binary units', () => { assert.equal(formatBytes(1024), '1 KiB'); assert.equal(formatBytes(0), '0 B'); });
