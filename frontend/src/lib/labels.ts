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
