import { useSyncExternalStore } from 'react'
import { getConnection, subscribeConnection } from '../services/api'
import { getBridgeState, subscribeBridge } from '../services/extensionBridge'

/** Backend connection + which endpoints the backend hasn't implemented yet. */
export function useConnection() {
  const c = useSyncExternalStore(subscribeConnection, getConnection)
  return { ...c, missingEndpoints: Object.keys(c.missing) }
}

/** Live state of the Chrome extension bridge. */
export function useExtensionBridge() {
  return useSyncExternalStore(subscribeBridge, getBridgeState)
}
