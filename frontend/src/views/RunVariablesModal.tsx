import { useState } from 'react';
import { ArrowUpRight, Command, X } from 'lucide-react';
import type { Skill } from '../types';

export function RunVariablesModal({ skill, placeholders, onClose, onRun }: { skill: Skill; placeholders: string[]; onClose: () => void; onRun: (vars: Record<string, string>) => void }) {
  const [values, setValues] = useState<Record<string, string>>(() => Object.fromEntries(placeholders.map((p) => [p, ''])));
  const ready = placeholders.every((p) => (values[p] ?? '').trim().length > 0);
  return <div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-label="Run with variables"><div className="modal-top"><div className="modal-icon"><Command size={20} /></div><button className="icon-button" onClick={onClose} aria-label="Close"><X size={17} /></button></div><span className="eyebrow">RUN WITH VARIABLES</span><h2>{skill.name}</h2><p className="muted">This skill was recorded with placeholder values. Fill them in before running.</p>{placeholders.map((p) => <label key={p}>{p}<input value={values[p] ?? ''} onChange={(event) => setValues((current) => ({ ...current, [p]: event.target.value }))} placeholder={`Value for ${p}`} /></label>)}<button className="primary-button full" disabled={!ready} onClick={() => onRun(values)}><ArrowUpRight size={16} />Run skill</button></div></div>;
}
