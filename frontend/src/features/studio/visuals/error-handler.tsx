import { ApiError } from "@/lib/api/transport";
export function errorText(error: unknown): string {
  if (!(error instanceof ApiError)) {
    return "We couldn't confirm the result. Check your image history before submitting again.";
  }

  switch (error.code) {
    case "image_limit":
      return "Image creation limit reached. This project has used all its available image attempts. Your existing images are safe.";

    case "image_pending":
      return "Another image is already processing. Check its progress before creating another image.";

    case "image_rate_limited":
      return "The AI image service is temporarily rate-limited. Check your image history before trying later.";

    case "provider_unavailable":
      return "The AI image service couldn't complete your request. Your existing images are unchanged.";

    case "image_outcome_unknown":
      return "We couldn't confirm whether the AI image request completed. Check your image history before attempting another request.";

    case "source_unavailable":
      return "The selected image or video frame is unavailable. Choose another starting image.";

    case "invalid_image_output":
      return "The AI service returned an image we couldn't validate. Your existing images are safe.";
  }

  if (error.status === 429) {
    return "Image creation is currently limited. Check your project image limit or try again later.";
  }

  if (error.status === 409) {
    return "Another image request is processing or your project changed. Check your images before continuing.";
  }

  if (error.status === 0) {
    return "We couldn't confirm whether your request reached the server. Check your image history before submitting again.";
  }

  return "The image request couldn't be completed. Check your image history for the latest status.";
}
