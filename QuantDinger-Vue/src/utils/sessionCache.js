/**
 * Lightweight sessionStorage cache with TTL — used by data-heavy pages (e.g.
 * the AI asset analysis dashboard) to render *instantly* from cache on
 * re-entry while a background refresh quietly updates the store.
 *
 * Design notes:
 *  - sessionStorage (not localStorage) so the cache dies with the browser tab.
 *    Market data goes stale within minutes; we don't want yesterday's heatmap
 *    surfacing tomorrow morning.
 *  - Every entry is namespaced under `qd:cache:<key>` so it never clashes with
 *    other libs writing to sessionStorage.
 *  - All operations are wrapped in try/catch — sessionStorage can throw in
 *    incognito / cross-origin iframes / quota-exceeded states. We must never
 *    let a cache failure crash the page.
 *  - `read(key)` returns `null` for cache miss / corrupt / expired entries.
 *    Callers should treat `null` as "go fetch".
 */

const NAMESPACE = 'qd:cache:'

function _k (key) {
  return NAMESPACE + String(key)
}

/**
 * Save value under key. `ttlMs` is the freshness window in milliseconds;
 * after this window `read()` returns null even though the underlying entry
 * still sits in sessionStorage. Defaults to 5 minutes which is conservative
 * for low-volatility data like market sentiment / sector heatmaps.
 */
export function write (key, value, ttlMs = 5 * 60 * 1000) {
  try {
    const payload = JSON.stringify({
      v: value,
      e: Date.now() + Math.max(0, Number(ttlMs) || 0)
    })
    sessionStorage.setItem(_k(key), payload)
  } catch (_) {
    // ignore — quota / privacy mode
  }
}

/**
 * Read fresh value or null. `null` means: cache miss, expired, or unreadable.
 */
export function read (key) {
  try {
    const raw = sessionStorage.getItem(_k(key))
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object') return null
    if (typeof parsed.e !== 'number' || Date.now() > parsed.e) {
      // expired — opportunistically delete to keep storage clean
      try { sessionStorage.removeItem(_k(key)) } catch (_) {}
      return null
    }
    return parsed.v
  } catch (_) {
    return null
  }
}

/**
 * Get the timestamp (ms since epoch) at which the cached entry expires, or
 * 0 if there is no entry. Useful for "should we still skip the refresh?"
 * decisions in `activated()` hooks.
 */
export function expiresAt (key) {
  try {
    const raw = sessionStorage.getItem(_k(key))
    if (!raw) return 0
    const parsed = JSON.parse(raw)
    return (parsed && typeof parsed.e === 'number') ? parsed.e : 0
  } catch (_) {
    return 0
  }
}

/**
 * True if the entry exists and is not yet expired.
 */
export function isFresh (key) {
  return expiresAt(key) > Date.now()
}

/**
 * Drop a single cache entry.
 */
export function invalidate (key) {
  try { sessionStorage.removeItem(_k(key)) } catch (_) {}
}

export default { read, write, expiresAt, isFresh, invalidate }
