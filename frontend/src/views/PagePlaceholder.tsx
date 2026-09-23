import { Gauge } from 'lucide-react';

export function PagePlaceholder({ page, message }: { page: string; message?: string }) { return <section className="page-placeholder"><div className="placeholder-icon"><Gauge size={24} /></div><h2>{page}</h2><p>{message || 'Not part of the local record-and-replay workflow yet.'}</p>{!message && <span className="muted">Nothing to configure here</span>}</section> }
