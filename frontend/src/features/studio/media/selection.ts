export const MAX_FILES = 20;
export const MAX_FILE_BYTES = 2 * 1024 ** 3;
export const ACCEPT_VIDEO = ".mp4,.webm,.mov,.m4v,video/mp4,video/webm,video/quicktime,video/x-m4v";
const extensions = /\.(mp4|webm|mov|m4v)$/i;
const types = new Set(["video/mp4", "video/webm", "video/quicktime", "video/x-m4v"]);

export function fileKey(file: File): string {
  return JSON.stringify([file.name, file.size, file.lastModified]);
}

export function selectVideos(existing: File[], incoming: File[]) {
  const files = [...existing];
  const keys = new Set(files.map(fileKey));
  const errors: string[] = [];
  for (const file of incoming) {
    let reason = "";
    if (!extensions.test(file.name) || (file.type && !types.has(file.type))) reason = "Choose an MP4, WebM, MOV, or M4V video.";
    else if (!file.size) reason = "This file is empty. Choose a video with content.";
    else if (file.size > MAX_FILE_BYTES) reason = "This file exceeds 2 GiB. Choose a smaller video.";
    else if (keys.has(fileKey(file))) reason = "Already selected. Remove it before adding it again.";
    else if (files.length >= MAX_FILES) reason = "The library holds 20 videos. Remove a video to add another.";
    if (reason) errors.push(`${file.name}: ${reason}`);
    else { files.push(file); keys.add(fileKey(file)); }
  }
  return { files, errors, added: files.length - existing.length };
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB"];
  const index = bytes > 0 ? Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), 3) : 0;
  return `${new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(bytes / 1024 ** index)} ${units[index]}`;
}
