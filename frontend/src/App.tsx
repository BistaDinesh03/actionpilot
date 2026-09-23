import { useEffect, useState } from 'react';
import { Check, CircleHelp } from 'lucide-react';
import { API } from './lib/api';
import { hostname } from './lib/labels';
import { NAV_ITEMS } from './nav';
import type { AgentPlan, CommandResult, Run, Skill, Step } from './types';
import { ActivityView } from './views/ActivityView';
import { CommandView } from './views/CommandView';
import { ConnectionsView } from './views/ConnectionsView';
import { DeleteSkillModal } from './views/DeleteSkillModal';
import { MemoryView } from './views/MemoryView';
import { PagePlaceholder } from './views/PagePlaceholder';
import { RecordingView } from './views/RecordingView';
import { ReviewModal } from './views/ReviewModal';
import { RoutinesView } from './views/RoutinesView';
import { RunVariablesModal } from './views/RunVariablesModal';
import { RunView } from './views/RunView';
import { RunsHistory } from './views/RunsHistory';
import { SkillsView } from './views/SkillsView';
import { TeachModal } from './views/TeachModal';

export default function App() {
  const [page, setPage] = useState('Command');
  const [skills, setSkills] = useState<Skill[]>([]);
  const [command, setCommand] = useState('');
  const [result, setResult] = useState<CommandResult | null>(null);
  const [teachOpen, setTeachOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [review, setReview] = useState(false);
  const [sessionId, setSessionId] = useState('');
  const [reviewSkillId, setReviewSkillId] = useState('');
  const [taskName, setTaskName] = useState('');
  const [description, setDescription] = useState('');
  const [steps, setSteps] = useState<Step[]>([]);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState(false);
  const [activeRun, setActiveRun] = useState<Run | null>(null);
  const [gmailStatus, setGmailStatus] = useState('not_connected');
  const [emailSent, setEmailSent] = useState(false);
  const [runVarsOpen, setRunVarsOpen] = useState<{ skill: Skill; placeholders: string[] } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<Skill | null>(null);

  useEffect(() => { fetch(`${API}/api/skills`).then((response) => response.json()).then(setSkills).catch(() => setSkills([])); }, []);
  useEffect(() => { fetch(`${API}/api/gmail/status`).then((response) => response.json()).then((data) => setGmailStatus(data.status)).catch(() => setGmailStatus('error')); }, []);
  useEffect(() => { if (!activeRun) return; const poll = () => fetch(`${API}/api/runs/${activeRun.id}`).then((response) => response.json()).then(setActiveRun).catch(() => undefined); poll(); const timer = window.setInterval(poll, 500); return () => window.clearInterval(timer); }, [activeRun?.id]);
  useEffect(() => { const receive = (event: MessageEvent) => { if (event.data?.source !== 'actionpilot-extension' || !event.data.action) return; const next = event.data.action; setSteps((current) => { const last = current[current.length - 1]; if (last && last.type === 'type' && next.type === 'type' && JSON.stringify(last.target) === JSON.stringify(next.target)) return [...current.slice(0, -1), next]; return [...current, next]; }); }; window.addEventListener('message', receive); return () => window.removeEventListener('message', receive); }, []);
  const startTeaching = async () => { setError(''); try { const response = await fetch(`${API}/api/teach/start`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: taskName.trim(), description }) }); if (!response.ok) throw new Error('Could not start a teaching session.'); const session = await response.json(); setSessionId(session.session_id); setSteps([]); setTeachOpen(false); setRecording(true); window.postMessage({ source: 'actionpilot', type: 'START_TEACHING', sessionId: session.session_id }, '*'); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not start teaching.'); } };
  const stopTeaching = async () => { setError(''); try { const response = await fetch(`${API}/api/teach/${sessionId}/finish`, { method: 'POST' }); if (!response.ok) throw new Error('Could not finish the teaching session.'); const skill = await response.json(); setReviewSkillId(skill.id); setSteps(skill.steps); setRecording(false); setReview(true); } catch (cause) { setError(cause instanceof Error ? cause.message : 'Could not finish teaching.'); } };
  const saveReview = async () => { await fetch(`${API}/api/skills/${reviewSkillId}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: taskName, description, domains: [...new Set(steps.map((step) => hostname(step.url)).filter((domain) => domain !== 'Browser'))], steps }) }); setReview(false); setSaved(true); setTimeout(() => setSaved(false), 2500); fetch(`${API}/api/skills`).then((response) => response.json()).then(setSkills); };
  const runCommand = async () => { if (!command.trim()) return; const response = await fetch(`${API}/api/command`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ command }) }); setResult(await response.json()); };
  const runAgent = async (plan: AgentPlan) => { const response = await fetch(`${API}/api/agent/execute`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ plan, approved: false }) }); const body = await response.json(); if (body.status === 'queued' && body.run_id) { try { const run = await (await fetch(`${API}/api/runs/${body.run_id}`)).json(); setActiveRun(run); setPage('Runs'); return; } catch { /* fall through to preview update */ } } if (result) setResult({ ...result, output: body.output, run_id: body.run_id, message: body.message || result.message }); };
  const sendEmail = async (email: CommandResult) => { if (!email.recipient) return; const response = await fetch(`${API}/api/gmail/send`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ to: email.recipient, subject: email.subject || '', body: email.body || '', message_id: email.message_id, approved: true }) }); if (response.ok) { setEmailSent(true); setTimeout(() => setEmailSent(false), 3000); } };
  const connectGmail = () => { window.location.href = `${API}/api/gmail/connect`; };
  const disconnectGmail = async () => { const response = await fetch(`${API}/api/gmail/disconnect`, { method: 'POST' }); if (response.ok) setGmailStatus('not_connected'); };
  const runSkill = async (skill: Skill, variables: Record<string, string> = {}) => { const response = await fetch(`${API}/api/runs`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ skill_id: skill.id, task_name: skill.name, variables }) }); if (response.ok) { setActiveRun(await response.json()); setPage('Runs'); } };
  const placeholdersFor = (skill: Skill): string[] => {
    const found = new Set<string>();
    const re = /\{\{\s*([A-Za-z0-9_]+)\s*\}\}/g;
    for (const step of skill.steps) {
      if (typeof step.value !== 'string') continue;
      let m: RegExpExecArray | null;
      while ((m = re.exec(step.value)) !== null) found.add(m[1]);
    }
    return [...found];
  };
  const requestRunSkill = (skill: Skill) => {
    const placeholders = placeholdersFor(skill);
    if (placeholders.length === 0) { runSkill(skill, {}); return; }
    setRunVarsOpen({ skill, placeholders });
  };
  const openRun = async (run: Run) => {
    const fresh = await fetch(`${API}/api/runs/${run.id}`).then((response) => response.json()).catch(() => null);
    setActiveRun(fresh && Array.isArray(fresh.steps) ? fresh : run);
  };
  return <div className="app-shell"><aside className="sidebar"><div className="brand"><div className="brand-mark"><svg width="19" height="19" viewBox="0 0 128 128" aria-hidden="true"><path d="M44 34 L92 64 L44 94 Z" fill="#102118"/><circle cx="97" cy="31" r="10" fill="#F0655A"/></svg></div><div><strong>ActionPilot</strong><span>LOCAL AUTOMATION</span></div></div><div className="workspace-label">WORKSPACE</div><nav>{NAV_ITEMS.map(({ label, Icon, special }) => <button className={page === label ? 'nav-item active' : 'nav-item'} onClick={() => { if (special === 'teach') { setTeachOpen(true); return; } setPage(label); }} key={label}><Icon size={17} /><span>{label}</span></button>)}</nav><div className="sidebar-bottom"><div className="status-line"><span className="status-dot" />{recording ? 'Recording browser' : 'Automation ready'}</div><div className="version">v0.1.0 local-first</div></div></aside><main className="main"><header className="topbar"><div><span className="eyebrow">{recording ? 'RECORDING' : page.toUpperCase()}</span><h1>{recording ? taskName : page === 'Command' ? 'What should I do?' : page}</h1></div><div className="top-actions"><button className="icon-button" title="How to use ActionPilot" onClick={() => window.open('http://127.0.0.1:8000/guide/USER_GUIDE.md', '_blank')}><CircleHelp size={18} /></button><button className="avatar">AP</button></div></header>{recording ? <RecordingView taskName={taskName} steps={steps} onStop={stopTeaching} error={error} /> : page === 'Command' ? <CommandView command={command} setCommand={setCommand} runCommand={runCommand} result={result} setResult={setResult} skills={skills} onTeach={() => setTeachOpen(true)} onRun={requestRunSkill} onSend={sendEmail} onAgentRun={runAgent} /> : page === 'Skills' ? <SkillsView skills={skills} onTeach={() => setTeachOpen(true)} onRun={requestRunSkill} onRequestDelete={setDeleteTarget} /> : page === 'Runs' && activeRun ? <RunView run={activeRun} setRun={setActiveRun} /> : page === 'Connections' ? <ConnectionsView status={gmailStatus} onConnect={connectGmail} onDisconnect={disconnectGmail} /> : page === 'Activity' ? <ActivityView /> : page === 'Memory' ? <MemoryView /> : page === 'Routines' ? <RoutinesView /> : page === 'Runs' ? <RunsHistory onOpen={openRun} /> : <PagePlaceholder page={page} />}</main>{deleteTarget && <DeleteSkillModal skill={deleteTarget} onClose={() => setDeleteTarget(null)} onConfirm={() => { setDeleteTarget(null); window.location.reload(); }} />}{runVarsOpen && <RunVariablesModal skill={runVarsOpen.skill} placeholders={runVarsOpen.placeholders} onClose={() => setRunVarsOpen(null)} onRun={(vars) => { const s = runVarsOpen.skill; setRunVarsOpen(null); runSkill(s, vars); }} />}{teachOpen && <TeachModal name={taskName} setName={setTaskName} description={description} setDescription={setDescription} onClose={() => setTeachOpen(false)} onStart={startTeaching} error={error} />}{review && <ReviewModal name={taskName} steps={steps} setSteps={setSteps} onSave={saveReview} onClose={() => setReview(false)} />}{saved && <div className="toast"><Check size={16} />Skill saved to your local library</div>}{emailSent && <div className="toast"><Check size={16} />Email sent</div>}</div>;
}
