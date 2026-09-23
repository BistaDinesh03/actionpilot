import { useEffect, useState } from 'react';
import { getJson } from '../lib/api';
import type { Run } from '../types';

function relTime(iso: string): string {
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

function progressLabel(run: Run): string {
  const done = run.steps.filter((step) => step.status === 'completed').length;
  const total = Math.max(run.plan?.length ?? 0, run.steps.length, run.status === 'waiting_confirmation' ? run.current_step + 1 : 0);
  return total > 0 ? `${done} / ${total}` : '—';
}

// Runs page, no active run: reopen any run from existing run storage.
export function RunsHistory({ onOpen }: { onOpen: (run: Run) => void }) {
  const [runs, setRuns] = useState<Run[] | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    getJson<Run[]>('/api/runs')
      .then((all) => { setRuns(Array.isArray(all) ? all : []); setError(false); })
      .catch(() => { setRuns((previous) => previous ?? []); setError(true); });
  }, []);
  return (
    <section className="section runs-history">
      <div className="section-heading"><div><span className="eyebrow">HISTORY</span><h2>Recent runs</h2></div></div>
      {runs === null ? <p className="muted">Loading runs…</p>
        : runs.length === 0 ? <p className="muted">{error ? 'Couldn\'t reach the local backend to load runs.' : 'No runs yet. Run a Skill to watch it step by step — with screenshots, video, and a full timeline.'}</p>
        : (
          <div className="runs-history-list">
            {runs.slice(0, 30).map((run) => (
              <button className="runs-history-row" key={run.id} onClick={() => onOpen(run)} title={`Open run ${run.id}`}>
                <span className="runs-history-name">{run.task_name || 'Untitled run'}</span>
                <span className={`run-state ${run.status}`}>{run.status.replace('_', ' ')}</span>
                <span className="runs-history-steps">{progressLabel(run)}</span>
                <span className="runs-history-time">{run.created_at ? relTime(run.created_at) : ''}</span>
              </button>
            ))}
          </div>
        )}
    </section>
  );
}
