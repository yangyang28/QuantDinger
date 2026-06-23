import request from '@/utils/request'

const api = {
  brokerMarket: '/api/policy/broker-market'
}

/**
 * Fetch the broker x market x market_type compatibility policy.
 *
 * Returned shape (see backend `app/services/broker_market_policy.to_dict`):
 *   {
 *     broker_markets: { ibkr: { USStock: ['spot'] }, ... },
 *     long_only_brokers: ['alpaca', 'ibkr'],
 *     bot_type_markets: { grid: ['Crypto', 'Forex'], ... },
 *     live_market_categories: ['Crypto', 'Forex', 'USStock']
 *   }
 *
 * Backend wraps this in `{ code: 1, data: ... }` like every other endpoint.
 */
export function getBrokerMarketPolicy () {
  return request({
    url: api.brokerMarket,
    method: 'get'
  })
}
