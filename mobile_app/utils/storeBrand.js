import { connectionService } from '../services/api';
import { getEffectiveApiBase, normalizeApiBase } from './apiBase';

export { normalizeApiBase };

/** Logo URLs from Django often use localhost; rewrite to the same origin as API calls (tunnel / LAN IP). */
export function resolveStoreLogoUrl(apiBase, logoPath, logoUrlAbsolute) {
  const base = normalizeApiBase(apiBase);
  if (!base) return '';

  const path = logoPath != null ? String(logoPath).trim() : '';
  if (path.startsWith('/')) {
    return `${base}${path}`;
  }

  const abs = logoUrlAbsolute != null ? String(logoUrlAbsolute).trim() : '';
  if (!abs) return '';

  try {
    const u = new URL(abs);
    return `${base}${u.pathname}${u.search || ''}`;
  } catch {
    return abs;
  }
}

/** Store logo (Store profile) + system name (Kiosk config) from /api/mobile/store-info/. */
export async function fetchStoreBrandAssets() {
  try {
    const apiBase = await getEffectiveApiBase();
    const data = await connectionService.fetchStoreInfo();
    if (!data?.store) {
      return { logoUrl: '', systemName: '' };
    }
    let logoUrl = resolveStoreLogoUrl(apiBase, data.store.logo_path, data.store.logo_url);
    const bust = Number(data.store.logo_cache_key);
    if (logoUrl && bust > 0) {
      logoUrl += `${logoUrl.includes('?') ? '&' : '?'}v=${bust}`;
    }
    const systemName = String(data.store.system_name || '').trim();
    return { logoUrl, systemName };
  } catch {
    return { logoUrl: '', systemName: '' };
  }
}
