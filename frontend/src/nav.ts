import { Activity, BookOpen, Command, Gauge, History, Layers3, Library, Radio, Settings } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

export type NavGroup = 'tasks' | 'library' | 'system';
export type NavItem = { label: string; Icon: LucideIcon; group: NavGroup; special?: 'teach' };

// Single registry for the sidebar. Future agents/workflows register a page here
// and mount a matching route in App.
// Grouping communicates the product hierarchy without redesigning navigation:
// tasks first (Command -> Runs), then the libraries, then system/less-used pages.
export const NAV_GROUP_LABELS: Record<NavGroup, string> = {
  tasks: 'TASKS',
  library: 'LIBRARY',
  system: 'SYSTEM',
};

export const NAV_ITEMS: NavItem[] = [
  { label: 'Command', Icon: Command, group: 'tasks' },
  { label: 'Runs', Icon: History, group: 'tasks' },
  { label: 'Skills', Icon: Library, group: 'library' },
  { label: 'Activity', Icon: Activity, group: 'library' },
  { label: 'Memory', Icon: BookOpen, group: 'library' },
  { label: 'Routines', Icon: Gauge, group: 'system' },
  { label: 'Connections', Icon: Layers3, group: 'system' },
  { label: 'Teach', Icon: Radio, group: 'system', special: 'teach' },
  { label: 'Settings', Icon: Settings, group: 'system' },
];
