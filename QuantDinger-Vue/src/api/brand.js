import request from '@/utils/request'

/**
 * Fetch public branding / legal / contact configuration.
 *
 * The endpoint is public (no auth) so we can load it on the login page as
 * well, before any user signs in.  Backend reads BRAND_* / MOBILE_APP_* env
 * vars; empty values fall back to the bundled defaults.
 */
export function getBrandConfig () {
  return request({
    url: '/api/settings/brand-config',
    method: 'get'
  })
}
