import { useEffect, useState } from 'react';
import { ArrowUpRight, Gauge, Plus } from 'lucide-react';
import { API } from '../lib/api';

type Routine = { id: string; name: string; prompt: string; schedule: string; enabled: boolean };

export function RoutinesView() {
  const [items, setItems] = useState<Routine[] | null>(null);
  const [error, setError] = useState(false);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');
  const load = () => fetch(`${API}/api/routines`)
    .then((response) => { if (!response.ok) throw new Error('load failed'); return response.json(); })
    .then((data) => { setItems(Array.isArray(data) ? data : []); setError(false); })
    .catch(() => { setItems((previous) => previous ?? []); setError(true); });
  useEffect(() => { load(); }, []);
  const add = async () => {
    if (!name || !prompt) return;
    const response = await fetch(`${API}/api/routines`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name, prompt, schedule: 'manual', enabled: true }) });
    if (response.ok) { setItems([...(items ?? []), await response.json()]); setName(''); setPrompt(''); }
  };
  const run = async (id: string) => {
    await fetch(`${API}/api/routines/${id}/run`, { method: 'POST' });
    load();
  };
  return (
    <section className="page-placeholder routine-view">
      <div className="placeholder-icon"><Gauge size={24} /></div>
      <h2>Routines</h2>
      <p>Save a prompt and rerun it later with the same plan and approval rules.</p>
      <div className="memory-form">
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Morning Research" />
        <textarea value={prompt} onChange={(event) => setPrompt(event.target.value)} placeholder="Research recent AI automation posts and give me 5 ideas." />
        <button className="primary-button" onClick={add}><Plus size={16} />Create routine</button>
      </div>
      {items === null ? <p className="muted">Loading routines…</p>
        : error && items.length === 0 ? <p className="muted">Couldn't reach the local backend to load routines.</p>
        : items.length === 0 ? <p className="muted empty-state">No routines yet — saved prompts appear here and always ask before acting.</p>
        : (
          <div className="full-skill-list">
            {items.map((item) => (
              <div key={item.id}>
                <span><strong>{item.name}</strong><small>{item.schedule} · {item.enabled ? 'Enabled' : 'Paused'}</small></span>
                <button className="card-run" onClick={() => run(item.id)}>Run now <ArrowUpRight size={15} /></button>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}
