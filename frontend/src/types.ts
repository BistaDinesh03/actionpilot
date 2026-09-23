export type Target = { tag?: string; role?: string; name?: string; text?: string; label?: string; placeholder?: string; test_id?: string; css?: string; xpath?: string };
export type Step = { type: string; label: string; timestamp?: string; url?: string; title?: string; target?: Target; value?: string; risk_level?: string };
export type Skill = { id: string; name: string; description: string; steps: Step[]; domains: string[]; created_at: string; last_run: string | null; runs: number; success_rate: number };
export type EmailContact = { name: string; email: string };
export type AgentStep = { tool: string; action: string; risk: string; parameters?: Record<string, unknown> };
export type AgentPlan = { request: string; intent: string; confidence: number; steps: AgentStep[]; variables: Record<string, string>; requires_confirmation: boolean; message?: string };
export type CommandResult = { matched: boolean; intent?: string; skill_id?: string; confidence?: number; variables?: Record<string, string>; message?: string; skill?: Skill; plan?: Step[]; agent_plan?: AgentPlan; output?: { sources?: Array<{ title: string; url: string; excerpt: string }>; ideas?: string[] }; requires_confirmation?: boolean; run_id?: string; recipient_query?: string; recipient?: EmailContact; subject?: string; body?: string; candidates?: EmailContact[]; connected?: boolean; draft_id?: string; message_id?: string };
export type RunStep = { step_index: number; label?: string; action_type?: string; status: string; error?: string; screenshot_path?: string; url?: string; title?: string; started_at?: string; verification?: string | { passed?: boolean; summary?: string } };
export type Run = { id: string; skill_id: string; task_name: string; status: string; current_step: number; current_action?: string; error?: string; screenshot_path?: string; created_at?: string; steps: RunStep[]; plan?: Array<Record<string, unknown>>; output?: Record<string, unknown> };

export type Approval = { id: string; run_id: string; step_index: number; kind: string; summary: string; detail?: Record<string, unknown>; status: string; created_at: string; resolved_at: string | null };
export type ActivityEvent = { id: string; event: string; detail: string; created_at: string };
