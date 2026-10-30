
export interface PublicStoryboardCut {
  editorial_reason?: string;
  window_index: number;
  media_id?: string;
  source_window_index?: number;
  playback_order?: number;
  start_seconds: number;
  end_seconds: number;
}

export interface PublicStoryboard {
  target_seconds: number;
  total_seconds: number;
  render_seconds?: number;
  cuts: PublicStoryboardCut[];
}

const EPSILON = 1e-6;

const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function isRecord(
  value: unknown,
): value is Record<string, unknown> {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value)
  );
}

function isFiniteNumber(
  value: unknown,
): value is number {
  return (
    typeof value === "number" &&
    Number.isFinite(value)
  );
}

function isIndex(value: unknown): value is number {
  return (
    typeof value === "number" &&
    Number.isSafeInteger(value) &&
    value >= 0
  );
}

function optionalIndex(
  value: unknown,
  field: string,
): number | undefined {
  if (value == null) return undefined;

  if (!isIndex(value)) {
    throw new Error(`Invalid ${field}.`);
  }

  return value;
}

function parseCut(
  value: unknown,
  index: number,
): PublicStoryboardCut {
  if (!isRecord(value)) {
    throw new Error(`Invalid cut at index ${index}.`);
  }

  const {
    window_index,
    media_id,
    source_window_index,
    playback_order,
    start_seconds,
    end_seconds,
  } = value;

  if (!isIndex(window_index)) {
    throw new Error("Invalid window_index.");
  }

  if (
    !isFiniteNumber(start_seconds) ||
    !isFiniteNumber(end_seconds) ||
    start_seconds < 0 ||
    end_seconds <= start_seconds
  ) {
    throw new Error(`Invalid time range in cut ${index + 1}.`);
  }

  if (
    media_id != null &&
    (typeof media_id !== "string" ||
      !UUID_PATTERN.test(media_id))
  ) {
    throw new Error("Invalid media_id.");
  }

  if (value.editorial_reason != null && (typeof value.editorial_reason !== "string" || !value.editorial_reason.trim())) {
    throw new Error("Invalid editorial_reason.");
  }

  const sourceWindow = optionalIndex(
    source_window_index,
    "source_window_index",
  );

  const playbackOrder = optionalIndex(
    playback_order,
    "playback_order",
  );

  return {
    ...(typeof value.editorial_reason === "string" ? { editorial_reason: value.editorial_reason } : {}),
    window_index,
    start_seconds,
    end_seconds,
    ...(typeof media_id === "string"
      ? { media_id }
      : {}),
    ...(sourceWindow !== undefined
      ? { source_window_index: sourceWindow }
      : {}),
    ...(playbackOrder !== undefined
      ? { playback_order: playbackOrder }
      : {}),
  };
}

export function parsePublicStoryboard(
  value: unknown,
): PublicStoryboard {
  if (!isRecord(value)) {
    throw new Error("Storyboard must be a JSON object.");
  }

  const {
    target_seconds,
    total_seconds,
    render_seconds,
    cuts: rawCuts,
  } = value;

  if (
    !isFiniteNumber(target_seconds) ||
    target_seconds <= 0 ||
    target_seconds > 120
  ) {
    throw new Error("Invalid storyboard target duration.");
  }

  if (
    !isFiniteNumber(total_seconds) ||
    total_seconds <= 0
  ) {
    throw new Error("Invalid storyboard total duration.");
  }

  if (
    !Array.isArray(rawCuts) ||
    rawCuts.length < 1 ||
    rawCuts.length > 12
  ) {
    throw new Error("Storyboard requires 1–12 cuts.");
  }

  const cuts = rawCuts.map(parseCut);

  const windowIds = new Set(
    cuts.map((cut) => cut.window_index),
  );

  if (windowIds.size !== cuts.length) {
    throw new Error("Duplicate window_index.");
  }

  const calculatedTotal = cuts.reduce(
    (sum, cut) =>
      sum + (cut.end_seconds - cut.start_seconds),
    0,
  );

  if (
    calculatedTotal > target_seconds + EPSILON ||
    Math.abs(calculatedTotal - total_seconds) > EPSILON
  ) {
    throw new Error("Storyboard timeline is inconsistent.");
  }

  if (
    render_seconds != null &&
    (!isFiniteNumber(render_seconds) ||
      render_seconds <= 0 ||
      render_seconds > target_seconds + EPSILON)
  ) {
    throw new Error("Invalid render duration.");
  }

  return {
    target_seconds,
    total_seconds,
    cuts,
    ...(typeof render_seconds === "number"
      ? { render_seconds }
      : {}),
  };
}
