"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import type { MediaAsset } from "@/lib/api/contracts";
import { uploadMedia } from "@/lib/api/media";
import { ApiError } from "@/lib/api/transport";

import { formatBytes } from "./selection";
import { projectMediaKey, useProjectMedia } from "./hooks/use-project-media";
import {
  MAX_AI_MEDIA_SELECTION,
  useEditorStore,
  useSelectedMediaIds,
} from "../store/use-editor-store";
interface PersistedMediaProps {
  projectId: string;
  files: File[];
  onSaved: (files: File[]) => void;
  onBusy: (busy: boolean) => void;
}

export function PersistedMedia({
  projectId,
  files,
  onSaved,
  onBusy,
}: PersistedMediaProps) {
  const queryClient = useQueryClient();
  const mediaQuery = useProjectMedia(projectId);

  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const selectedMediaIds = useSelectedMediaIds(projectId);
  const toggleMediaSelection = useEditorStore(
    (state) => state.toggleMediaSelection,
  );
  const uploadController = useRef<AbortController | null>(null);

  const uploadMutation = useMutation({
    mutationFn: ({
      submitted,
      signal,
    }: {
      submitted: File[];
      signal: AbortSignal;
    }) => uploadMedia(projectId, submitted, signal),

    // Never automatically repeat a potentially persisted upload.
    retry: false,
  });

  // Stop the browser request when leaving the project.
  // This does not guarantee cancellation on the backend.
  useEffect(() => {
    return () => {
      uploadController.current?.abort();
    };
  }, [projectId]);

  const items = mediaQuery.data ?? [];
  const uploading = uploadMutation.isPending;

  async function upload() {
    if (!files.length || uploadController.current || uncertain) {
      return;
    }

    const controller = new AbortController();
    const submitted = [...files];

    uploadController.current = controller;

    setError("");
    setMessage("Sending videos and waiting for server confirmation…");
    onBusy(true);

    try {
      const result = await uploadMutation.mutateAsync({
        submitted,
        signal: controller.signal,
      });

      // Only confirmed server responses reach this point.
      onSaved(submitted);

      setMessage(`${result.items.length} videos saved by the backend.`);

      // Update existing cache with confirmed backend records.
      queryClient.setQueryData<MediaAsset[]>(
        projectMediaKey(projectId),
        (previous) => {
          if (!previous) return previous;

          const savedIds = new Set(result.items.map((item) => item.id));

          return [
            ...previous.filter((item) => !savedIds.has(item.id)),
            ...result.items,
          ];
        },
      );

      // Reconcile cache with the authoritative backend.
      void queryClient.invalidateQueries({
        queryKey: projectMediaKey(projectId),
      });
    } catch (err) {
      const api = err instanceof ApiError ? err : null;

      const prefix =
        api?.fileIndex !== undefined ? `File ${api.fileIndex + 1}: ` : "";

      setError(
        `${prefix}${err instanceof Error ? err.message : "Upload failed."}`,
      );
      setMessage("");

      // An interrupted request might have completed server-side.
      if (
        !api ||
        (api.status === 0 &&
          !["upload_limit", "configuration_error", "invalid_project"].includes(
            api.code,
          )) ||
        api.status >= 500
      ) {
        setUncertain(true);
      }
    } finally {
      uploadController.current = null;
      onBusy(false);
    }
  }

  return (
    <div className="media-persisted">
      <h3 className="text-sm font-medium">Saved to this project</h3>

      <p className="mt-2 text-xs text-muted-foreground">
        Upload limits: 10 videos, 128 MiB each, 500 MiB total. Server limits may
        be lower.
      </p>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          className="button button-primary disabled:opacity-50"
          disabled={!files.length || uploading || uncertain}
          onClick={upload}
        >
          {uploading ? "Uploading…" : "Upload selected"}
        </button>

        {uploading && (
          <button
            type="button"
            className="button button-secondary"
            onClick={() => uploadController.current?.abort()}
          >
            Cancel request
          </button>
        )}

        <button
          type="button"
          className="media-remove"
          disabled={mediaQuery.isFetching || uploading}
          onClick={() => {
            void mediaQuery.refetch();
          }}
        >
          Refresh saved media
        </button>
      </div>

      <p role="status" className="mt-2 text-xs text-primary">
        {message}

        {mediaQuery.isPending
          ? " Loading saved media…"
          : mediaQuery.isFetching
            ? " Refreshing saved media…"
            : ""}
      </p>

      {error && (
        <p role="alert" className="media-errors">
          {error}
        </p>
      )}

      {mediaQuery.isError && (
        <p role="alert" className="media-errors">
          {mediaQuery.error instanceof Error
            ? mediaQuery.error.message
            : "Could not load saved media."}
        </p>
      )}

      {uncertain && (
        <div className="media-errors">
          <p>
            The server may have saved these files. Refresh and review saved
            media before submitting again. Cancellation does not roll back
            server work.
          </p>

          <button
            type="button"
            className="media-remove"
            onClick={() => setUncertain(false)}
          >
            I reviewed saved media; allow another upload
          </button>
        </div>
      )}

      {!mediaQuery.isPending && !mediaQuery.isError && !items.length && (
        <p className="mt-3 text-xs text-muted-foreground">
          No saved videos yet.
        </p>
      )}
      <p className="mt-2 text-xs text-muted-foreground">
        {selectedMediaIds.length} of {MAX_AI_MEDIA_SELECTION} videos selected
        for AI Director.
      </p>
      <ul className="media-list" aria-label="Saved project media">
        {items.map((item) => (
          <li className="media-file" key={item.id}>
            <span className="media-file-type">Saved</span>

            <h3>{item.original_filename}</h3>

            <p>
              {formatBytes(item.size_bytes)}
              {" · "}
              {item.duration_seconds.toFixed(2)} s
            </p>

            <p>
              {item.video.width}
              {" × "}
              {item.video.height}
              {" · "}
              {item.video.codec}
            </p>

            <p className="break-all">Media ID: {item.id}</p>

            <label className="mt-3 flex items-center gap-2 text-xs">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={selectedMediaIds.includes(item.id)}
                disabled={
                  !selectedMediaIds.includes(item.id) &&
                  selectedMediaIds.length >= MAX_AI_MEDIA_SELECTION
                }
                onChange={() => toggleMediaSelection(projectId, item.id)}
              />

              <span>Use in AI first cut</span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
