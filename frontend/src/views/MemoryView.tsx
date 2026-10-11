import { useEffect, useState } from 'react';
import { BookOpen, Plus, Trash2 } from 'lucide-react';
import { API } from '../lib/api';

type MemoryItem = { id: string; type: string; title: string; value: string };

export function MemoryView() {
  const [items, setItems] = useState<MemoryItem[] | null>(null);
  const [error, setError] = useState(false);
  const [title, setTitle] = useState('');
  const [value, setValue] = useState('');
  useEffect(() => {
    fetch(`${API}/api/memory`)
      .then((response) => { if (!response.ok) throw new Error('load failed'); return response.json(); })
      .then((data) => { setItems(Array.isArray(data) ? data : []); setError(false); })
      .catch(() => { setItems((previous) => previous ?? []); setError(true); });
  }, []);
  const add = async () => {
    if (!title || !value) return;
    const response = await fetch(`${API}/api/memory`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ type: 'user_preference', title, value }) });
    if (response.ok) { setItems([await response.json(), ...(items ?? [])]); setTitle(''); setValue(''); }
  };
  const remove = async (id: string) => {
    await fetch(`${API}/api/memory/${id}`, { method: 'DELETE' });
    setItems((items ?? []).filter((item) => item.id !== id));
  };
  return (
    <section className="page-placeholder memory-view">
      <div className="placeholder-icon"><BookOpen size={24} /></div>
      <h2>What does ActionPilot remember?</h2>
      <p>Only explicit preferences and saved routines belong here — nothing is guessed or tracked.</p>
      <div className="memory-form">
        <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Preference title" aria-label="Preference title" />
        <textarea value={value} onChange={(event) => setValue(event.target.value)} placeholder="When I ask for content ideas, include a hook and why it may work." aria-label="Preference details" />
        <button className="primary-button" onClick={add}><Plus size={16} />Save memory</button>
      </div>
      {items === null ? <p className="muted">Loading memory…</p>
        : error && items.length === 0 ? <p className="muted">Couldn't reach the local backend to load memory.</p>
        : items.length === 0 ? <p className="muted empty-state">Nothing saved yet — add a preference and ActionPilot will use it the next time it plans a task.</p>
        : (
          <div className="full-skill-list">
            {items.map((item) => (
              <div key={item.id}>
                <span><strong>{item.title}</strong><small>{item.type === 'user_preference' ? 'preference' : item.type} · {item.value}</small></span>
                <button className="delete-step" onClick={() => remove(item.id)} title="Forget this memory" aria-label={`Forget ${item.title}`}><Trash2 size={14} /></button>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}
