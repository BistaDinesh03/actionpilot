import { useEffect, useRef, useState } from 'react';
import { Check, ShieldCheck, Square } from 'lucide-react';
import { API, fetchPendingApprovals, resolveApproval } from '../lib/api';
import { runPhase } from '../lib/labels';
import type { Approval, Run, RunStep } from '../types';

export function RunView({ run, setRun }: { run: Run; setRun: (run: Run | null) => void }) {
  const [selectedStep, setSelectedStep] = useState<number | null>(null);
  const [videoAvailable, setVideoAvailable] = useState<boolean>(true);
  const [previewNonce, setPreviewNonce] = useState<number>(0);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const videoRef = useRef<HTMLVideoElement | null>(null);
  useEffect(() => { setVideoAvailable(true); setSelectedStep(null); }, [run.id]);

  const terminal = ['completed', 'failed', 'stopped'].includes(run.status);
  const verification = (() => {
    const fromOutput = (run.output as any)?.result?.verification;
    if (fromOutput && typeof fromOutput === 'object') return fromOutput as { passed?: boolean; summary?: string };
    for (const step of [...run.steps].reverse()) {
      if (!step.verification) continue;
      try {
        const parsed = typeof step.verification === 'string' ? JSON.parse(step.verification) : step.verification;
        if (parsed && typeof parsed === 'object') return parsed as { passed?: boolean; summary?: string };
      } catch { /* ignore malformed verification */ }
    }
    return null;
  })();
  const failedStep = run.steps.find((s) => s.status === 'failed');
  const defaultSelected = failedStep ? failedStep.step_index : (run.steps.length > 0 ? run.steps[run.steps.length - 1].step_index : null);
  const activeIndex = selectedStep !== null ? selectedStep : defaultSelected;
  const activeStep = activeIndex !== null ? run.steps.find((s) => s.step_index === activeIndex) ?? null : null;
  const runningStep = run.steps.find((s) => s.status === 'running') ?? (run.steps.length > 0 ? run.steps[run.steps.length - 1] : null);
  const done = run.steps.filter((s) => s.status === 'completed').length;
  const total = Math.max(run.plan?.length ?? 0, run.steps.length, run.status === 'waiting_confirmation' ? run.current_step + 1 : 0);
  const percent = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0;
  const summary = run.status === 'completed'
    ? (verification && verification.passed === false ? `All ${total} steps finished — verification flagged an issue.` : `All ${total} steps finished${verification ? ' and verified' : ''}.`)
    : run.status === 'failed' ? `Run failed after ${done} of ${total} steps.`
    : `Stopped after ${done} of ${total} steps.`;

  useEffect(() => {
    if (terminal) { setApprovals([]); return; }
    const poll = () => fetchPendingApprovals(run.id).then(setApprovals).catch(() => undefined);
    poll();
    const timer = window.setInterval(poll, 700);
    return () => window.clearInterval(timer);
  }, [run.id, terminal]);

  const control = async (action: 'pause' | 'resume' | 'stop') => {
    const response = await fetch(`${API}/api/runs/${run.id}/${action}`, { method: 'POST' });
    if (response.ok) setRun(await response.json());
  };

  const decide = async (approvalId: string, decision: 'approve' | 'reject') => {
    const approval = await resolveApproval(approvalId, decision).catch(() => null);
    if (!approval) return;
    setApprovals((current) => current.filter((item) => item.id !== approvalId));
    const refreshed = await fetch(`${API}/api/runs/${run.id}`).then((response) => response.json()).catch(() => null);
    if (refreshed) setRun(refreshed);
  };

  const seekVideoTo = (step: RunStep) => {
    if (!videoRef.current || !step.started_at || !run.created_at) return;
    try {
      const offsetMs = new Date(step.started_at).getTime() - new Date(run.created_at).getTime();
      if (offsetMs >= 0) videoRef.current.currentTime = offsetMs / 1000;
    } catch { /* ignore */ }
  };

  const onStepClick = (step: RunStep) => {
    setSelectedStep(step.step_index);
    seekVideoTo(step);
  };
  const retryPreview = () => { setPreviewNonce((n) => n + 1); };

  return <section className="run-panel">
    <div className="run-header">
      <div>
        <span className="eyebrow">{runPhase(run)}</span>
        <h2>{run.task_name}</h2>
        <p className="muted">{terminal ? summary : (run.current_action || 'Starting browser...')}</p>
      </div>
      <div className="run-controls">
        <button className="secondary-button" onClick={() => setRun(null)} title="Back to run history">← All runs</button>
        {run.status === 'paused' ? <button className="primary-button" onClick={() => control('resume')}>Resume</button>
          : !['completed', 'failed', 'stopped'].includes(run.status) && <button className="secondary-button" onClick={() => control('pause')}>Pause</button>}
        {!['completed', 'failed', 'stopped'].includes(run.status) && <button className="stop-button" onClick={() => control('stop')}><Square size={14} />Stop</button>}
      </div>
    </div>

    <div className="run-status">
      <span className={`run-state ${run.status}`}>{run.status.replace('_', ' ')}</span>
      {run.error && <span className="error-text">{run.error}</span>}
    </div>

    <div className="run-progress" title={`${done} of ${total} steps completed`}>
      <div className="run-progress-bar" style={{ width: `${percent}%` }} />
    </div>
    <div className="run-progress-meta"><span>{done} / {total} steps</span><span>{percent}%</span></div>

    <div className="run-body">
      <div className="run-left">
        {approvals.map((approval) => (
          <div className="approval-card" key={approval.id}>
            <div className="approval-head"><ShieldCheck size={18} /><div><span className="eyebrow">APPROVAL REQUIRED</span><strong>{approval.summary}</strong></div></div>
            <p className="muted">Step {approval.step_index + 1} is paused while the agent waits for your decision.</p>
            <div className="approval-actions">
              <button className="secondary-button" onClick={() => decide(approval.id, 'reject')}>Reject</button>
              <button className="primary-button" onClick={() => decide(approval.id, 'approve')}><Check size={15} />Approve</button>
            </div>
          </div>
        ))}
        <div className="step-list">
          {run.steps.map((step) => {
            const isActive = step.step_index === activeIndex;
            const cls = `step-row${isActive ? ' active' : ''}${step.status === 'failed' ? ' failed' : ''}${step.status === 'running' ? ' running' : ''}`;
            return <div className={cls} key={step.step_index} onClick={() => onStepClick(step)} title="Click to view this step">
              <span className="step-number">{String(step.step_index + 1).padStart(2, '0')}</span>
              <span>{step.label || step.error || 'Browser action'}</span>
              <span className={`step-type ${step.status}`}>{step.status}</span>
            </div>;
          })}
        </div>

        {activeStep && (
          <div className="step-detail">
            <div className="step-detail-head">
              <strong>Step {String(activeStep.step_index + 1).padStart(2, '0')}</strong>
              <span className={`step-type ${activeStep.status}`}>{activeStep.status}</span>
            </div>
            <div className="step-detail-meta">
              <span><small>type</small> {activeStep.action_type || 'browser'}</span>
              {activeStep.url && <span><small>url</small> {activeStep.url}</span>}
              {activeStep.title && <span><small>title</small> {activeStep.title}</span>}
            </div>
            {activeStep.error && <p className="error-text">{activeStep.error}</p>}
          </div>
        )}

        {run.status === 'failed' && run.screenshot_path && <div className="failure-detail">
          <strong>Run failed</strong>
          <span>{run.error}</span>
        </div>}
      </div>

      <div className="run-right">
        {terminal && videoAvailable && (
          <div className="run-video">
            <strong>Run recording</strong>
            <div className="video-frame"><video ref={videoRef} controls preload="metadata" src={`${API}/api/runs/${run.id}/video`} onError={() => setVideoAvailable(false)} /></div>
          </div>
        )}
        {!terminal && (
          <div className="run-live">
            <strong>Live preview</strong>
            {runningStep ? (
              <div className="preview-frame">
                <img src={`${API}/api/runs/${run.id}/step/${runningStep.step_index}/screenshot?t=${Date.now()}-${previewNonce}`} alt="Current step" onError={(e) => { (e.currentTarget as HTMLImageElement).setAttribute('data-missing', 'true'); (e.currentTarget as HTMLImageElement).style.display = 'none'; }} onLoad={(e) => { (e.currentTarget as HTMLImageElement).removeAttribute('data-missing'); (e.currentTarget as HTMLImageElement).style.display = ''; }} />
              </div>
            ) : (
              <div className="run-live-empty">Waiting for the first step…</div>
            )}
          </div>
        )}
        {activeStep && (
          <div className="run-preview">
            <strong>Step {String(activeStep.step_index + 1).padStart(2, '0')} preview</strong>
            <div className="preview-frame">
              <img
                src={`${API}/api/runs/${run.id}/step/${activeStep.step_index}/screenshot?t=${Date.now()}-${previewNonce}`}
                alt={`Step ${activeStep.step_index + 1} preview`}
                onError={(e) => { (e.currentTarget as HTMLImageElement).setAttribute('data-missing', 'true'); (e.currentTarget as HTMLImageElement).style.display = 'none'; }} onLoad={(e) => { (e.currentTarget as HTMLImageElement).removeAttribute('data-missing'); (e.currentTarget as HTMLImageElement).style.display = ''; }}
              />
              <div className="preview-missing">
                <span>Screenshot not available</span>
                <button className="secondary-button preview-retry" onClick={retryPreview}>Retry load</button>
              </div>
            </div>
          </div>
        )}
        {terminal && (
          <div className="run-result">
            <strong>Final result</strong>
            <div className="run-result-row"><span>Status</span><b className={`step-type ${run.status}`}>{run.status}</b></div>
            <div className="run-result-row"><span>Steps completed</span><b>{done} / {Math.max(total, done)}</b></div>
            <div className="run-result-row"><span>Evidence</span><b>{run.steps.filter((s) => s.screenshot_path).length} screenshots{videoAvailable ? ' + video' : ''}</b></div>
            {verification && <div className="run-result-row"><span>Verification</span><b className={verification.passed ? 'step-type completed' : 'step-type failed'}>{verification.passed ? 'Verified' : 'Not verified'}</b></div>}
            {verification?.summary && <div className="run-result-row"><span>Result</span><b>{verification.summary}</b></div>}
            {run.error ? <p className="error-text">{run.error}</p> : <p className="muted">{run.current_action || 'All steps finished.'}</p>}
          </div>
        )}
      </div>
    </div>
  </section>;
}
