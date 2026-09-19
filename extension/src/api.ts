import type { BrowserAction } from './types';

const API = 'http://127.0.0.1:8000';
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `ActionPilot API error (${response.status})`);
  return response.json() as Promise<T>;
}
export const startSession = (name: string, description: string) => request<{ session_id: string; name: string }>('/api/teach/start', { method: 'POST', body: JSON.stringify({ name, description }) });
export const sendAction = (sessionId: string, action: BrowserAction) => request<{ recorded: boolean; reason?: string }>(`/api/teach/${sessionId}/action`, { method: 'POST', body: JSON.stringify(action) });
export const finishSession = (sessionId: string) => request('/api/teach/' + sessionId + '/finish', { method: 'POST' });
export const health = () => request<{ status: string }>('/health');
