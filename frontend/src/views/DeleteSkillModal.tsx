import { useState } from 'react';
import { Trash2, X } from 'lucide-react';
import { API } from '../lib/api';
import type { Skill } from '../types';

export function DeleteSkillModal({ skill, onClose, onConfirm }: { skill: Skill; onClose: () => void; onConfirm: () => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const confirm = async () => {
    setBusy(true); setError('');
    try {
      const r = await fetch(`${API}/api/skills/${skill.id}`, { method: 'DELETE' });
      if (!r.ok) throw new Error('Could not delete skill.');
      onConfirm();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not delete skill.');
      setBusy(false);
    }
  };
  return <div className="modal-backdrop"><div className="modal"><div className="modal-top"><div className="modal-icon"><Trash2 size={20} /></div><button className="icon-button" onClick={onClose} disabled={busy}><X size={17} /></button></div><span className="eyebrow">DELETE SKILL</span><h2>{skill.name}</h2><p className="muted">This will permanently remove this skill and its {skill.steps.length} recorded action{skill.steps.length === 1 ? '' : 's'}. This cannot be undone.</p>{error && <p className="error-text">{error}</p>}<div className="modal-actions"><button className="secondary-button" onClick={onClose} disabled={busy}>Cancel</button><button className="danger-button" onClick={confirm} disabled={busy}>{busy ? 'Deleting…' : 'Delete skill'}</button></div></div></div>;
}
