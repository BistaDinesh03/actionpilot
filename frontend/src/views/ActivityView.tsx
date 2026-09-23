import { useEffect, useState } from 'react';
import { Waypoints } from 'lucide-react';
import { fetchActivity } from '../lib/api';
import type { ActivityEvent } from '../types';

function timeLabel(iso: string) {
  try {
    const date = new Date(iso);
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    const time = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return time;
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) return `Yesterday ${time}`;
    return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`;
  } catch {
    return '';
  }
}

export function ActivityView() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  useEffect(() => {
    const poll = () => fetchActivity(50)
      .then((next) => { setEvents(next); setLoading(false); setError(false); })
      .catch(() => { setLoading(false); setError(true); });
    poll();
    const timer = window.setInterval(poll, 3000);
    return () => window.clearInterval(timer);
  }, []);
  return <section className="page-placeholder activity-view">
    <div className="placeholder-icon"><Waypoints size={24} /></div>
    <h2>Activity</h2>
    <p>Every local decision ActionPilot records: runs, approvals, memory, and teaching.</p>
    {loading ? <span className="muted">Loading activity…</span> : events.length === 0 ? (error ? <span className="muted">Couldn't reach the local backend to load activity.</span> : <span className="muted">No activity yet. ActionPilot records important actions, approvals, and results here.</span>) : <div className="activity-list">{events.map((event) => <div className="activity-event" key={event.id}><span className={`activity-kind ${event.event}`}>{event.event.replace(/_/g, ' ')}</span><span className="activity-detail">{event.detail}</span><span className="activity-time">{timeLabel(event.created_at)}</span></div>)}</div>}
  </section>;
}
