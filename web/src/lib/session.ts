const KEY = "constellation.session";
// the server accepts exactly this shape; anything else in storage is ignored rather than sent
const VALID = /^[a-z0-9-]{8,64}$/;

// kept when storage is unavailable, so one page still uses one session
let kept: string | undefined;

function fresh(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID().toLowerCase();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

// one id per browser tab: the tab's memory lasts as long as the tab, and a new tab starts clean
export function sessionId(): string {
  try {
    const stored = sessionStorage.getItem(KEY);
    if (stored !== null && VALID.test(stored)) return stored;
  } catch {
    // storage can be blocked or throw (private windows, embedded frames); the page keeps its own id instead
  }
  kept ??= fresh();
  try {
    sessionStorage.setItem(KEY, kept);
  } catch {
    // a session that cannot be saved still works for this page load
  }
  return kept;
}
