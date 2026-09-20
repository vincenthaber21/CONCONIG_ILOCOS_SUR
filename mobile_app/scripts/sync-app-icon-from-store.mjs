#!/usr/bin/env node
/**
 * Syncs native/branding assets from Django GET /api/mobile/store-info/:
 *   - Store profile → Logo → assets/icon.png (launcher + adaptive foreground), favicon.png, splash.png
 *   - Kiosk config → System name → assets/generated-brand-meta.json (read by app.config.js for expo.name)
 *
 * Run before `eas build` / `expo prebuild`. EAS runs this via eas-build-post-install (non-fatal on failure).
 *
 * API base URL (first match wins):
 *   - STORE_API_BASE_URL env
 *   - --local  → LOCAL_IP from config.js
 *   - otherwise → PRODUCTION_URL from config.js
 */

import { writeFileSync, readFileSync, mkdirSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const mobileRoot = join(__dirname, '..');
const assetsDir = join(mobileRoot, 'assets');

function readUrlsFromConfig() {
  const text = readFileSync(join(mobileRoot, 'config.js'), 'utf8');
  const prod = text.match(/const\s+PRODUCTION_URL\s*=\s*['"]([^'"]+)['"]/);
  const local = text.match(/const\s+LOCAL_IP\s*=\s*['"]([^'"]+)['"]/);
  return {
    prodUrl: prod?.[1]?.trim().replace(/\/+$/, ''),
    localUrl: local?.[1]?.trim().replace(/\/+$/, ''),
  };
}

function resolveLogoUrl(apiBase, store) {
  const base = apiBase.replace(/\/+$/, '');
  const p = store?.logo_path?.trim?.();
  if (p?.startsWith('/')) return `${base}${p}`;
  const abs = store?.logo_url?.trim?.();
  if (!abs) return '';
  try {
    const u = new URL(abs);
    return `${base}${u.pathname}${u.search || ''}`;
  } catch {
    return abs;
  }
}

async function fetchStore(apiBase) {
  const url = `${apiBase.replace(/\/+$/, '')}/api/mobile/store-info/`;
  const res = await fetch(url, { headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`store-info HTTP ${res.status}`);
  return res.json();
}

async function download(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`logo HTTP ${res.status}`);
  return Buffer.from(await res.arrayBuffer());
}

async function toPng1024(buffer) {
  try {
    const { default: sharp } = await import('sharp');
    return await sharp(buffer)
      .resize(1024, 1024, {
        fit: 'contain',
        background: { r: 255, g: 255, b: 255, alpha: 0 },
      })
      .png()
      .toBuffer();
  } catch {
    console.warn(
      '[sync-brand] sharp not available or failed; writing raw icon bytes (prefer PNG in admin)',
    );
    return buffer;
  }
}

async function toSplashPng(logoRawBuffer) {
  const { default: sharp } = await import('sharp');
  const W = 1284;
  const H = 2778;
  const maxLogo = 560;
  const logoBuf = await sharp(logoRawBuffer)
    .resize(maxLogo, maxLogo, {
      fit: 'contain',
      background: { r: 255, g: 255, b: 255, alpha: 0 },
    })
    .png()
    .toBuffer();

  return sharp({
    create: {
      width: W,
      height: H,
      channels: 4,
      background: { r: 255, g: 255, b: 255, alpha: 1 },
    },
  })
    .composite([{ input: logoBuf, gravity: 'center' }])
    .png()
    .toBuffer();
}

async function main() {
  const { prodUrl, localUrl } = readUrlsFromConfig();
  const useLocal = process.argv.includes('--local');
  const apiBase =
    process.env.STORE_API_BASE_URL?.trim().replace(/\/+$/, '') ||
    (useLocal ? localUrl : prodUrl) ||
    prodUrl ||
    localUrl;

  if (!apiBase) {
    throw new Error(
      'No API base URL: set STORE_API_BASE_URL or LOCAL_IP / PRODUCTION_URL in config.js',
    );
  }

  console.log(`[sync-brand] Store info: ${apiBase}/api/mobile/store-info/`);
  const data = await fetchStore(apiBase);

  const systemName = (data?.store?.system_name || '').trim();
  mkdirSync(assetsDir, { recursive: true });
  writeFileSync(
    join(assetsDir, 'generated-brand-meta.json'),
    `${JSON.stringify({ system_name: systemName }, null, 2)}\n`,
    'utf8',
  );
  console.log(
    `[sync-brand] Wrote generated-brand-meta.json (system name: ${systemName || '(empty)'})`,
  );

  const logoUrl = resolveLogoUrl(apiBase, data?.store);

  if (!logoUrl) {
    console.warn('[sync-brand] No Store profile logo — icon/splash PNGs unchanged.');
    return;
  }

  console.log(`[sync-brand] Logo: ${logoUrl}`);
  const raw = await download(logoUrl);
  const pngIcon = await toPng1024(raw);

  writeFileSync(join(assetsDir, 'icon.png'), pngIcon);
  writeFileSync(join(assetsDir, 'favicon.png'), pngIcon);
  console.log('[sync-brand] Updated assets/icon.png (launcher + adaptive), favicon.png');

  try {
    const splashPng = await toSplashPng(raw);
    writeFileSync(join(assetsDir, 'splash.png'), splashPng);
    console.log('[sync-brand] Updated assets/splash.png');
  } catch (e) {
    console.warn('[sync-brand] Could not rebuild splash.png:', e?.message || e);
  }
}

main().catch((err) => {
  console.warn('[sync-brand] Skipped (build will use existing assets):', err?.message || err);
  process.exit(0);
});
