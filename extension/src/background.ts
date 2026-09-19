import { finishSession, sendAction, startSession, health } from './api';
import type { BrowserAction, RecorderState, RuntimeMessage } from './types';
let state: RecorderState = { status: 'idle' };
const broadcast = async (message: RuntimeMessage) => { const tabs = await chrome.tabs.query({}); await Promise.all(tabs.filter((tab) => tab.id).map((tab) => chrome.tabs.sendMessage(tab.id!, message).catch(() => undefined))); };
async function persist() { await chrome.storage.local.set({ actionpilot: state }); }
chrome.runtime.onMessage.addListener((message: RuntimeMessage, sender, respond) => { (async () => { try {
  if (message.type === 'GET_STATE') return respond(state);
  if (message.type === 'START_FROM_POPUP') { const session = await startSession(message.name, message.description); state = { status: 'recording', sessionId: session.session_id, name: session.name }; await persist(); await broadcast({ type: 'START_SESSION', sessionId: session.session_id, name: session.name }); return respond(state); }
  if (message.type === 'START_SESSION') { state = { status: 'recording', sessionId: message.sessionId, name: message.name }; await persist(); return respond(state); }
  if (message.type === 'ACTION' && state.status === 'recording' && state.sessionId) { await sendAction(state.sessionId, message.action); await broadcast({ type: 'ACTION_RECORDED', action: message.action }); return respond({ ok: true }); }
  if (message.type === 'STOP_SESSION' && state.sessionId) { const result = await finishSession(state.sessionId); state = { status: 'idle' }; await persist(); await broadcast({ type: 'STOP_SESSION' }); return respond(result); }
} catch (error) { state = { ...state, status: 'disconnected' }; await persist(); return respond({ error: error instanceof Error ? error.message : 'ActionPilot connection failed' }); } })(); return true; });
chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => { if (changeInfo.status === 'complete' && state.status === 'recording' && state.sessionId && tab.url && !tab.url.startsWith('chrome://')) { const action: BrowserAction = { type: 'navigate', timestamp: new Date().toISOString(), url: tab.url, title: tab.title || '' }; try { await sendAction(state.sessionId, action); } catch { state = { ...state, status: 'disconnected' }; await persist(); } } });
health().catch(() => { state = { status: 'disconnected' }; persist(); });
