import { Activity, BookOpen, Command, Gauge, History, Layers3, Library, Radio, Settings } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type NavItem = { label: string; Icon: LucideIcon; special?: 'teach' };

// Single registry for the sidebar. Future agents/workflows register a page here
// and mount a matching route in App.
export const NAV_ITEMS: NavItem[] = [
  { label: 'Command', Icon: Command },
  { label: 'Teach', Icon: Radio, special: 'teach' },
  { label: 'Skills', Icon: Library },
  { label: 'Runs', Icon: History },
  { label: 'Activity', Icon: Activity },
  { label: 'Memory', Icon: BookOpen },
  { label: 'Routines', Icon: Gauge },
  { label: 'Connections', Icon: Layers3 },
  { label: 'Settings', Icon: Settings },
];
