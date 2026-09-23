import type { ActivityEvent, Approval } from '../types';

export const API = 'http://localhost:8000';

export function getJson<T>(path: string): Promise<T> {
  return fetch(`${API}${path}`).then((response) => response.json() as Promise<T>);
}

export function fetchActivity(limit = 50): Promise<ActivityEvent[]> {
  return getJson<ActivityEvent[]>(`/api/activity?limit=${limit}`);
}

export function fetchPendingApprovals(runId: string): Promise<Approval[]> {
  const query = new URLSearchParams({ status: 'pending', run_id: runId });
  return getJson<Approval[]>(`/api/approvals?${query.toString()}`);
}

export function resolveApproval(approvalId: string, decision: 'approve' | 'reject'): Promise<Approval> {
  return fetch(`${API}/api/approvals/${approvalId}/${decision}`, { method: 'POST' }).then((response) => response.json() as Promise<Approval>);
}
