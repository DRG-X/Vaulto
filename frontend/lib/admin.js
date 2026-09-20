/**
 * Whether this user may see the admin surfaces.
 *
 * This is a UI convenience only — it decides whether to render a link, never
 * whether data is allowed out. The list is a NEXT_PUBLIC_ variable, so it is
 * in the browser bundle and anyone can read it or lie about it. The real gate
 * is ADMIN_USER_IDS on the backend, checked against the signed token.
 */
export function isAdmin(userId) {
  if (!userId) return false;
  const ids = (process.env.NEXT_PUBLIC_ADMIN_USER_IDS || "")
    .split(",")
    .map(s => s.trim())
    .filter(Boolean);
  return ids.includes(userId);
}
