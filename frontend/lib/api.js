const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// ── Auth helper ────────────────────────────────────────────────────────────────

function authHeaders(token) {
  return { "Authorization": `Bearer ${token}` };
}

/**
 * Fetch that cannot hang forever.
 *
 * The sign-in and onboarding screens block on these calls — they are all the
 * user can see. A backend that accepts the connection and then goes quiet
 * (a cold container, a dropped mobile connection) leaves a spinner spinning
 * with no way out, which reads as "the product is broken". A rejection gives
 * the screen something to say and a Retry button to offer.
 */
async function fetchWithTimeout(url, options = {}, timeoutMs = 20000) {
  if (typeof AbortController === "undefined") return fetch(url, options);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (err) {
    if (err?.name === "AbortError") {
      const timeout = new Error("The server took too long to respond.");
      timeout.status = 0;
      timeout.isTimeout = true;
      throw timeout;
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

async function handleResponse(res) {
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = err.detail;
    // FastAPI returns 422 detail as a list of field errors — join them into
    // something a person can act on instead of showing "[object Object]".
    const message = Array.isArray(detail)
      ? detail.map(d => d?.msg || String(d)).join(", ")
      : (typeof detail === "string" ? detail : null);
    const errorObj = new Error(message || "API request failed");
    errorObj.status = res.status;
    throw errorObj;
  }
  return res.json();
}

// ── User status / legacy ───────────────────────────────────────────────────────

/** Quick check: does this user have a saved profile? */
export async function checkUserStatus(token) {
  const res = await fetchWithTimeout(`${API_URL}/user/status`, {
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

export async function getUserProfile(token) {
  const res = await fetchWithTimeout(`${API_URL}/user/profile`, {
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

export async function createUserProfile(token, data) {
  const res = await fetchWithTimeout(`${API_URL}/user/profile`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

// ── Compare ────────────────────────────────────────────────────────────────────

/**
 * Sort modes the backend understands. `cheapest` maximises what the recipient
 * receives and is the honest default; the others exist because "best" is
 * genuinely personal — rent money wants `fastest`, savings want `best_rate`.
 */
export const SORT_MODES = {
  CHEAPEST: "cheapest",
  FASTEST: "fastest",
  LOWEST_FEE: "lowest_fee",
  BEST_RATE: "best_rate",
  BEST_VALUE: "best_value",
};

/**
 * Build the filter half of a comparison request.
 *
 * Only non-default values are sent. That keeps URLs and cache keys clean, and
 * means a request with no filters is byte-identical to the one the backend
 * treats as the default.
 */
function filterParams({ sortBy, maxEtaMinutes, payInMethod, payOutMethod, includePromo } = {}) {
  const out = {};
  if (sortBy && sortBy !== SORT_MODES.CHEAPEST) out.sort_by = sortBy;
  if (maxEtaMinutes) out.max_eta_minutes = String(maxEtaMinutes);
  if (payInMethod) out.pay_in_method = payInMethod;
  if (payOutMethod) out.pay_out_method = payOutMethod;
  if (includePromo === false) out.include_promo = "false";
  return out;
}

export async function compareProviders({
  amount, currency_from, currency_to,
  sortBy, maxEtaMinutes, payInMethod, payOutMethod, includePromo,
}) {
  const body = {
    amount: parseFloat(amount),
    currency_from,
    currency_to,
  };
  if (sortBy) body.sort_by = sortBy;
  if (maxEtaMinutes) body.max_eta_minutes = Number(maxEtaMinutes);
  if (payInMethod) body.pay_in_method = payInMethod;
  if (payOutMethod) body.pay_out_method = payOutMethod;
  if (includePromo === false) body.include_promo = false;

  const res = await fetch(`${API_URL}/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return handleResponse(res);
}

// ── /api/users ─────────────────────────────────────────────────────────────────

/** Upsert user row after Clerk sign-in/sign-up */
export async function syncUser(token, { clerk_id, email, full_name }) {
  const res = await fetchWithTimeout(`${API_URL}/api/users/sync`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify({ clerk_id, email, full_name }),
  });
  return handleResponse(res);
}

/** GET /api/users/me — returns full user row */
export async function getMe(token) {
  const res = await fetchWithTimeout(`${API_URL}/api/users/me`, {
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

/** PATCH /api/users/me — partial update */
export async function updateMe(token, data) {
  const res = await fetchWithTimeout(`${API_URL}/api/users/me`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

// ── /api/onboarding ────────────────────────────────────────────────────────────

export async function completeOnboarding(token, data) {
  const res = await fetchWithTimeout(`${API_URL}/api/onboarding/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

// ── /api/rates ─────────────────────────────────────────────────────────────────

/**
 * Live comparison for a corridor.
 *
 * Sorting and filtering happen on the SERVER, not here. That is not just tidier
 * — the backend picks which of a provider's pay-in/pay-out options to show
 * based on the active filter, so a speed filter switches Western Union to its
 * minutes-settled rail instead of dropping it. Re-sorting the returned rows in
 * the browser cannot do that, and would silently disagree with the "Fastest"
 * badge the backend computed.
 */
export async function getRates({
  from, to, amount,
  sortBy, maxEtaMinutes, payInMethod, payOutMethod, includePromo,
} = {}) {
  const params = new URLSearchParams({
    from,
    to,
    amount: String(amount),
    ...filterParams({ sortBy, maxEtaMinutes, payInMethod, payOutMethod, includePromo }),
  });
  const res = await fetch(`${API_URL}/api/rates?${params}`);
  return handleResponse(res);
}

// ── /api/providers ─────────────────────────────────────────────────────────────

/**
 * Every provider the engine knows about, from the registry itself.
 *
 * The client keeps no provider list of its own: one went stale the moment the
 * backend grew past three providers, and a stale list is worse than none —
 * it silently omits options the engine is already comparing.
 *
 * `corridor` is "AUD:INR" style and narrows to providers serving it.
 */
export async function listProviders({ corridor } = {}) {
  const params = new URLSearchParams();
  if (corridor) params.set("corridor", corridor);
  const qs = params.toString();
  const res = await fetch(`${API_URL}/api/providers${qs ? `?${qs}` : ""}`);
  return handleResponse(res);
}

// ── /api/comparisons ───────────────────────────────────────────────────────────

export async function saveComparison(token, data) {
  const res = await fetch(`${API_URL}/api/comparisons`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function listComparisons(token, { page = 1, limit = 20 } = {}) {
  const params = new URLSearchParams({ page, limit });
  const res = await fetch(`${API_URL}/api/comparisons?${params}`, {
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

// ── /api/alerts ────────────────────────────────────────────────────────────────

export async function createAlert(token, data) {
  const res = await fetch(`${API_URL}/api/alerts`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function listAlerts(token) {
  const res = await fetch(`${API_URL}/api/alerts`, {
    headers: authHeaders(token),
  });
  return handleResponse(res);
}

export async function updateAlert(token, id, data) {
  const res = await fetch(`${API_URL}/api/alerts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", ...authHeaders(token) },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}

export async function deleteAlert(token, id) {
  const res = await fetch(`${API_URL}/api/alerts/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const errorObj = new Error(err.detail || "Delete failed");
    errorObj.status = res.status;
    throw errorObj;
  }
  // 204 No Content — no body
}

export async function submitContactForm(data) {
  const res = await fetch(`${API_URL}/api/contact`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse(res);
}
