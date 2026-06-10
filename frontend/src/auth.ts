const TOKEN_KEY = 'caimp_token'
const ORG_KEY   = 'caimp_org_id'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? ''
}

export function getOrgId(): string {
  return localStorage.getItem(ORG_KEY) ?? ''
}

export function saveSession(accessToken: string, refreshToken: string): void {
  localStorage.setItem(TOKEN_KEY, accessToken)
  // Decode org_id from JWT payload (no library needed for reading)
  try {
    const [, payloadB64] = accessToken.split('.')
    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')))
    if (payload.org_id) localStorage.setItem(ORG_KEY, payload.org_id)
  } catch {
    // ignore decode errors
  }
  localStorage.setItem('caimp_refresh_token', refreshToken)
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(ORG_KEY)
  localStorage.removeItem('caimp_refresh_token')
}

export function isLoggedIn(): boolean {
  const token = getToken()
  if (!token) return false
  try {
    const [, payloadB64] = token.split('.')
    const payload = JSON.parse(atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/')))
    return payload.exp * 1000 > Date.now()
  } catch {
    return false
  }
}
