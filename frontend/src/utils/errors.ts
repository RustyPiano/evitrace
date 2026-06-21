export function extractErrorMessage(error: unknown, fallback: string): string {
  if (typeof error === "object" && error !== null && "response" in error) {
    const response = (error as { response?: { data?: { detail?: { message?: string } } } }).response;
    return response?.data?.detail?.message ?? fallback;
  }
  return fallback;
}
