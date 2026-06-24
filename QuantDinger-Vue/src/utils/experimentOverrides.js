/**
 * Normalize experiment tuner overrides for indicator # @param lines.
 * Backend may return nested indicatorParams or flat indicator_params.<name>.
 */

const INDICATOR_PARAMS_PREFIX = 'indicator_params.'
const INDICATOR_PARAMS_CAMEL_PREFIX = 'indicatorParams.'

export function extractIndicatorParamsFromOverrides (overrides) {
  const out = {}
  if (!overrides || typeof overrides !== 'object') return out

  const nested = overrides.indicatorParams || overrides.indicator_params
  if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
    Object.keys(nested).forEach(name => {
      if (name) out[name] = nested[name]
    })
  }

  Object.keys(overrides).forEach(key => {
    if (key === 'indicatorParams' || key === 'indicator_params') return
    let name = null
    if (key.startsWith(INDICATOR_PARAMS_PREFIX)) {
      name = key.slice(INDICATOR_PARAMS_PREFIX.length)
    } else if (key.startsWith(INDICATOR_PARAMS_CAMEL_PREFIX)) {
      name = key.slice(INDICATOR_PARAMS_CAMEL_PREFIX.length)
    }
    if (name) out[name] = overrides[key]
  })

  return out
}

/** Merge snapshot indicator_params (backtest truth) with override deltas. */
export function resolveExperimentIndicatorParams (overrides, snapshot) {
  const params = extractIndicatorParamsFromOverrides(overrides)
  if (!snapshot || typeof snapshot !== 'object') return params
  const snap = snapshot.indicator_params || snapshot.indicatorParams
  if (!snap || typeof snap !== 'object' || Array.isArray(snap)) return params
  return { ...snap, ...params }
}
