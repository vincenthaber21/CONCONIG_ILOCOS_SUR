import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL } from '../config';

const CUSTOM_SERVER_KEY = 'customServerUrl';

export function normalizeApiBase(url) {
  if (!url || !String(url).trim()) return '';
  return String(url).trim().replace(/\/+$/, '');
}

/** Resolved server root: Settings override when set, otherwise bundled config URL. */
export async function getEffectiveApiBase() {
  try {
    const custom = await AsyncStorage.getItem(CUSTOM_SERVER_KEY);
    const n = normalizeApiBase(custom);
    if (n) return n;
  } catch {
    // ignore
  }
  return normalizeApiBase(API_BASE_URL);
}
