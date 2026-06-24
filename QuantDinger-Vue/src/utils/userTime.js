import storage from 'store'
import { USER_INFO } from '@/store/mutation-types'

/** Return trimmed IANA id if valid, else '' */
export function normalizeIanaTimezone (tz) {
  const id = (tz && String(tz).trim()) || ''
  if (!id) return ''
  try {
    Intl.DateTimeFormat(undefined, { timeZone: id }).format(new Date())
    return id
  } catch (e) {
    return ''
  }
}

export function getUserTimezoneFromStorage () {
  try {
    const u = storage.get(USER_INFO) || {}
    return normalizeIanaTimezone(u.timezone)
  } catch (e) {
    return ''
  }
}

/**
 * Profile timezone (storage / Vuex) when set; otherwise browser IANA zone.
 */
export function getEffectiveUserTimezone (explicitTz) {
  const fromExplicit = normalizeIanaTimezone(explicitTz)
  if (fromExplicit) return fromExplicit
  const fromStorage = getUserTimezoneFromStorage()
  if (fromStorage) return fromStorage
  try {
    return normalizeIanaTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone)
  } catch (e) {
    return ''
  }
}

export function parseToDate (input) {
  if (input == null || input === '') return null
  if (input instanceof Date) {
    return isNaN(input.getTime()) ? null : input
  }
  if (typeof input === 'number') {
    const ms = input < 1e12 ? input * 1000 : input
    const d = new Date(ms)
    return isNaN(d.getTime()) ? null : d
  }
  if (typeof input === 'string') {
    const s = input.trim()
    if (/^\d+$/.test(s)) {
      const n = parseInt(s, 10)
      const ms = n < 1e12 ? n * 1000 : n
      const d = new Date(ms)
      return isNaN(d.getTime()) ? null : d
    }
    const d = new Date(s)
    return isNaN(d.getTime()) ? null : d
  }
  return null
}

/**
 * Format instant for display using profile timezone when set; otherwise browser default.
 */
export function formatUserDateTime (input, opts = {}) {
  const d = parseUtcAwareInstant(input)
  if (!d) return opts.fallback != null ? opts.fallback : '-'
  return formatInstantWithTimezone(d, {
    locale: opts.locale,
    withSeconds: true,
    timeZone: opts.timeZone
  })
}

/**
 * Parse API timestamps that are UTC instants but may lack a ``Z`` suffix.
 */
export function parseUtcAwareInstant (input) {
  if (input == null || input === '') return null
  if (input instanceof Date) {
    return isNaN(input.getTime()) ? null : input
  }
  if (typeof input === 'string') {
    const s = input.trim()
    if (!s) return null
    const isNaive = /^\d{4}[-/]\d{2}[-/]\d{2}[ T]\d{2}:\d{2}(:\d{2})?(\.\d+)?$/.test(s) &&
      !/[zZ]|[+-]\d{2}:?\d{2}$/.test(s)
    if (isNaive) {
      let iso = s.replace(/\//g, '-').replace(' ', 'T')
      if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(iso)) iso += ':00'
      const d = new Date(iso + 'Z')
      return isNaN(d.getTime()) ? null : d
    }
    return parseToDate(s)
  }
  return parseToDate(input)
}

/**
 * Format a backtest trade timestamp.
 *
 * Backend writes trade times via `timestamp.strftime('%Y-%m-%d %H:%M')` on
 * naive UTC-indexed pandas DataFrames (see backend_api_python/app/services/backtest.py).
 * That string carries no tz info, but its value IS UTC. `new Date(s)` would
 * interpret it as browser-local, producing a wrong wall clock for any user
 * outside UTC (e.g. CN users see "8 hours late").
 *
 * This helper:
 *   1. detects bare `YYYY-MM-DD HH:mm[:ss]` strings and parses them as UTC,
 *   2. falls back to `parseToDate` for tz-aware/ISO/number/Date inputs,
 *   3. renders using the user's profile timezone if set, else browser local.
 */
export function formatBacktestTime (input, opts = {}) {
  const d = parseUtcAwareInstant(input)
  if (!d) {
    return opts.fallback != null ? opts.fallback : '-'
  }
  return formatInstantWithTimezone(d, {
    locale: opts.locale,
    withSeconds: opts.withSeconds,
    timeZone: opts.timeZone
  })
}

function formatInstantWithTimezone (d, opts = {}) {
  const locale = opts.locale || (typeof navigator !== 'undefined' && navigator.language) || 'zh-CN'
  const tz = getEffectiveUserTimezone(opts.timeZone)
  const intlOpts = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }
  if (opts.withSeconds) intlOpts.second = '2-digit'
  if (tz) intlOpts.timeZone = tz
  try {
    return d.toLocaleString(locale, intlOpts)
  } catch (e) {
    try {
      const { timeZone, ...rest } = intlOpts
      return d.toLocaleString(locale, rest)
    } catch (e2) {
      return d.toLocaleString()
    }
  }
}

/**
 * Format instant in the browser's local timezone (ignores profile timezone override).
 * Use for audit-style timestamps (e.g. trade history) so wall clock matches the user's machine.
 */
export function formatBrowserLocalDateTime (input, opts = {}) {
  const d = input instanceof Date ? input : parseToDate(input)
  if (!d || isNaN(d.getTime())) return opts.fallback != null ? opts.fallback : '-'
  const locale = opts.locale || (typeof navigator !== 'undefined' && navigator.language) || 'zh-CN'
  const intlOpts = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false
  }
  if (opts.withSeconds) intlOpts.second = '2-digit'
  try {
    return d.toLocaleString(locale, intlOpts)
  } catch (e) {
    return d.toLocaleString()
  }
}

/**
 * Strategy / bot runtime logs: backend emits UTC ISO (Z) via ``to_utc_iso``.
 * Render in the user's profile timezone when set (e.g. Asia/Shanghai); pass
 * ``opts.timeZone`` from Vuex when localStorage ``User-Info`` may be stale.
 */
export function formatStrategyLogTime (input, opts = {}) {
  const d = parseUtcAwareInstant(input)
  if (!d) return opts.fallback != null ? opts.fallback : String(input || '')
  return formatInstantWithTimezone(d, {
    withSeconds: true,
    locale: opts.locale,
    timeZone: opts.timeZone
  })
}
