const STORAGE_KEY = "afa.adminKey";

export function getAdminKey(): string | null {
  try {
    return localStorage.getItem(STORAGE_KEY) || null;
  } catch {
    return null;
  }
}

export function setAdminKey(k: string): void {
  try {
    localStorage.setItem(STORAGE_KEY, k);
  } catch {
    /* storage unavailable */
  }
}

export function clearAdminKey(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* storage unavailable */
  }
}
