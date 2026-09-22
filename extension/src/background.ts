import { finishSession, sendAction, startSession, health } from './api';
import type { BrowserAction, RecorderState, RuntimeMessage } from './types';
let state: RecorderState = { status: 'idle' };

// MV3 service workers are killed after ~30 seconds of inactivity. Without
// rehydrating from storage on every wake-up, `state` resets to 'idle' and
// every subsequent ACTION message is silently dropped by the status check.
// This is the root cause of recordings that only capture the initial
// navigate and lose every click/input after the first 30 seconds.
async function rehydrate(): Promise<void> {
  try {
    const stored = await chrome.storage.local.get('actionpilot');
    if (stored && stored.actionpilot) {
      state = stored.actionpilot as RecorderState;
    }
  } catch {
    /* storage unavailable; keep whatever state we have */
  }
}

// Rehydrate on service-worker startup.
rehydrate();

// Also rehydrate on every incoming message. This must complete before the
// message handler inspects `state`, so we expose the promise and await it
// inside each branch that depends on state.status or state.sessionId.
chrome.runtime.onMessage.addListener((_m, _s, _r) => { rehydrate(); return false; });
const broadcast = async (message: RuntimeMessage) => { const tabs = await chrome.tabs.query({}); await Promise.all(tabs.filter((tab) => tab.id).map((tab) => chrome.tabs.sendMessage(tab.id!, message).catch(() => undefined))); };
async function persist() { await chrome.storage.local.set({ actionpilot: state }); }
chrome.runtime.onMessage.addListener((message: RuntimeMessage, sender, respond) => { (async () => { try {
  if (message.type === 'GET_STATE') { await rehydrate(); return respond(state); }
  if (message.type === 'START_FROM_POPUP') { const session = await startSession(message.name, message.description); state = { status: 'recording', sessionId: session.session_id, name: session.name }; await persist(); await broadcast({ type: 'START_SESSION', sessionId: session.session_id, name: session.name }); return respond(state); }
  if (message.type === 'START_SESSION') { state = { status: 'recording', sessionId: message.sessionId, name: message.name }; await persist(); return respond(state); }
  if (message.type === 'ACTION') { await rehydrate(); if (state.status === 'recording' && state.sessionId) { await sendAction(state.sessionId, message.action); await broadcast({ type: 'ACTION_RECORDED', action: message.action }); return respond({ ok: true }); } return respond({ ok: false, reason: 'not recording' }); }
  if (message.type === 'STOP_SESSION' && state.sessionId) { const result = await finishSession(state.sessionId); state = { status: 'idle' }; await persist(); await broadcast({ type: 'STOP_SESSION' }); return respond(result); }
} catch (error) { state = { ...state, status: 'disconnected' }; await persist(); return respond({ error: error instanceof Error ? error.message : 'ActionPilot connection failed' }); } })(); return true; });
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => { await rehydrate(); if (changeInfo.status === 'complete' && state.status === 'recording' && state.sessionId && tab.url && !tab.url.startsWith('chrome://')) { const action: BrowserAction = { type: 'navigate', timestamp: new Date().toISOString(), url: tab.url, title: tab.title || '' }; try { await sendAction(state.sessionId, action); } catch { state = { ...state, status: 'disconnected' }; await persist(); } } });
health().catch(() => { if (state.status !== 'recording') { state = { status: 'disconnected' }; persist(); } });
