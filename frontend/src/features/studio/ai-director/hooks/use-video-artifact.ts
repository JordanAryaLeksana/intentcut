
"use client";

import { useEffect, useRef, useState } from "react";
import { downloadAIArtifact } from "@/lib/api/artifacts";

export const MAX_PREVIEW_BYTES = 100 * 1024 * 1024;

type VideoPreview =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "ready"; url: string }
  | { status: "error"; message: string };

export function useVideoArtifact(
  projectId: string,
  jobId: string,
  artifactId: string,
  sizeBytes: number,
) {
  const [preview, setPreview] = useState<VideoPreview>({
    status: "idle",
  });

  const controllerRef = useRef<AbortController | null>(null);
  const objectUrlRef = useRef<string | null>(null);
  const mountedRef = useRef(false);

  useEffect(() => {
    mountedRef.current = true;

    return () => {
      mountedRef.current = false;
      controllerRef.current?.abort();

      if (objectUrlRef.current) {
        URL.revokeObjectURL(objectUrlRef.current);
        objectUrlRef.current = null;
      }
    };
  }, []);

  async function load() {
    if (controllerRef.current || objectUrlRef.current) {
      return;
    }

    if (
      !Number.isSafeInteger(sizeBytes) ||
      sizeBytes <= 0 ||
      sizeBytes > MAX_PREVIEW_BYTES
    ) {
      setPreview({
        status: "error",
        message: "Video exceeds the supported preview size.",
      });
      return;
    }

    const controller = new AbortController();
    controllerRef.current = controller;

    setPreview({ status: "loading" });

    try {
      const blob = await downloadAIArtifact(
        projectId,
        jobId,
        artifactId,
        controller.signal,
      );

      if (controller.signal.aborted || !mountedRef.current) {
        return;
      }

      if (blob.size !== sizeBytes) {
        throw new Error("Downloaded video size does not match artifact metadata.");
      }

      if (blob.type && blob.type !== "video/mp4") {
        throw new Error("Unexpected video content type.");
      }

      const url = URL.createObjectURL(blob);

      if (controller.signal.aborted || !mountedRef.current) {
        URL.revokeObjectURL(url);
        return;
      }

      objectUrlRef.current = url;
      setPreview({ status: "ready", url });
    } catch (error) {
      if (!mountedRef.current) return;

      if (controller.signal.aborted) {
        setPreview({ status: "idle" });
      } else {
        setPreview({
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "Unable to load video.",
        });
      }
    } finally {
      if (controllerRef.current === controller) {
        controllerRef.current = null;
      }
    }
  }

  function cancel() {
    controllerRef.current?.abort();
    setPreview({ status: "idle" });
  }

  return {
    preview,
    load,
    cancel,
  };
}
