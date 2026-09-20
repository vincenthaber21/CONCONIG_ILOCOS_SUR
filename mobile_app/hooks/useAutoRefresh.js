import { useEffect, useRef, useCallback } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import { AppState } from 'react-native';

/**
 * useAutoRefresh
 *
 * Automatically calls `onRefresh` at the given interval (ms) while the screen
 * is focused AND the app is in the foreground.  Also fires immediately when
 * the screen comes into focus so stale data is replaced straight away.
 *
 * @param {() => void | Promise<void>} onRefresh  - data-fetch callback
 * @param {number} [interval=30000]               - polling interval in ms
 * @param {boolean} [enabled=true]                - set to false to pause polling
 */
export function useAutoRefresh(onRefresh, interval = 30000, enabled = true) {
  const timerRef = useRef(null);
  const appStateRef = useRef(AppState.currentState);
  const isFocusedRef = useRef(false);

  const startPolling = useCallback(() => {
    if (timerRef.current) return; // already running
    timerRef.current = setInterval(() => {
      if (isFocusedRef.current && appStateRef.current === 'active' && enabled) {
        onRefresh();
      }
    }, interval);
  }, [onRefresh, interval, enabled]);

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  // Handle app going to background / foreground
  useEffect(() => {
    const subscription = AppState.addEventListener('change', (nextState) => {
      appStateRef.current = nextState;
      if (nextState === 'active' && isFocusedRef.current && enabled) {
        // App came back to foreground – refresh immediately then restart timer
        onRefresh();
        stopPolling();
        startPolling();
      } else if (nextState !== 'active') {
        stopPolling();
      }
    });

    return () => {
      subscription.remove();
      stopPolling();
    };
  }, [onRefresh, enabled, startPolling, stopPolling]);

  // Handle screen focus / blur (tab switch or navigation)
  useFocusEffect(
    useCallback(() => {
      isFocusedRef.current = true;
      if (enabled) {
        onRefresh(); // immediate refresh on focus
        startPolling();
      }
      return () => {
        isFocusedRef.current = false;
        stopPolling();
      };
    }, [onRefresh, enabled, startPolling, stopPolling])
  );
}
