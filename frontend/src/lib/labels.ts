import type { Run, Step } from '../types';

export function targetLabel(step: Step) { return step.target?.name || step.target?.label || step.target?.placeholder || step.target?.text || step.target?.role || step.url || 'Browser action'; }
export function stepLabel(step: Step) { const value = step.value ? ` “${step.value}”` : ''; return `${step.type[0].toUpperCase()}${step.type.slice(1)} ${targetLabel(step)}${value}`; }
export function hostname(url?: string) { try { return url ? new URL(url).hostname : 'Browser'; } catch { return 'Browser'; } }

// Live agent phase shown while a run is on screen.
export function runPhase(run: Run): string {
  switch (run.status) {
    case 'queued': return 'PLANNING';
    case 'running': return 'ACTING';
    case 'waiting_confirmation': return 'WAITING FOR APPROVAL';
    case 'paused': return 'PAUSED';
    case 'completed': return 'COMPLETE';
    case 'failed': return 'FAILED';
    case 'stopped': return 'STOPPED';
    default: return run.status.toUpperCase();
  }
}

// Single human label for a run status chip (history rows and RunView).
export function statusLabel(status: string): string {
  return status === 'waiting_confirmation' ? 'waiting for approval' : status.replace(/_/g, ' ');
}

// First human-readable line of an error: skips traceback frames and the exception class.
export function errorHeadline(error: string | null | undefined): string {
  if (!error) return '';
  for (const raw of error.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith('Traceback') || line.startsWith('File ') || /^[\s^]+$/.test(line)) continue;
    const exception = /^[\w.]+(?:Error|Exception):\s*(.+)$/.exec(line);
    return exception && exception[1].trim() ? exception[1].trim() : line;
  }
  return error.trim();
}

// Timeline state for a run step: internal run states never reach the UI.
export function stepStatusLabel(step: { step_index: number; status: string }, run: { status: string; current_step: number }, approvalSteps: number[] = []): string {
  if (step.status !== 'waiting_confirmation') return statusLabel(step.status);
  if (['completed', 'failed', 'stopped'].includes(run.status)) return 'not run';
  return step.step_index === run.current_step || approvalSteps.includes(step.step_index) ? 'waiting for approval' : 'pending';
}

// Compact "how long ago" label shared by run history and skills.
export function relTime(iso: string | null | undefined): string {
  if (!iso) return '';
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return '';
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return 'just now';
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}
