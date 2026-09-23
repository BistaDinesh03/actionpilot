import { ArrowUpRight, Plus, Trash2 } from 'lucide-react';
import { API } from '../lib/api';
import { relTime } from '../lib/labels';
import type { Skill } from '../types';

function usageLabel(skill: Skill): string {
  return skill.last_run ? `last run ${relTime(skill.last_run)}` : 'never run';
}

export function SkillsView({ skills, onTeach, onRun, onRequestDelete }: { skills: Skill[]; onTeach: () => void; onRun: (skill: Skill) => void; onRequestDelete: (skill: Skill) => void }) {
  return (
    <section className="section skills-page">
      <div className="section-heading">
        <div>
          <span className="eyebrow">LIBRARY</span>
          <h2>Your reusable skills</h2>
          <p className="muted skills-sub">Recorded browser workflows you can rerun, export as tests, or delete.</p>
        </div>
        <button className="primary-button" onClick={onTeach}><Plus size={16} />Teach a task</button>
      </div>
      {skills.length === 0
        ? <p className="muted">No skills yet — record your first workflow to get started.</p>
        : (
          <div className="full-skill-list skills-list">
            {skills.map((skill) => (
              <div key={skill.id}>
                <span className="skills-row-text">
                  <strong>{skill.name}</strong>
                  <small>{skill.steps.length} recorded actions · {skill.domains.join(', ') || 'Local browser'} · {usageLabel(skill)}</small>
                  {skill.description && <small className="skill-desc">{skill.description}</small>}
                </span>
                <span className="skills-row-actions">
                  <button className="card-run" disabled={skill.steps.length === 0} title={skill.steps.length === 0 ? 'No recorded steps to run' : 'Run this skill'} onClick={() => onRun(skill)}>Run <ArrowUpRight size={15} /></button>
                  <button className="card-run" onClick={() => { const a = document.createElement('a'); a.href = `${API}/api/skills/${skill.id}/export/playwright`; a.download = ''; document.body.appendChild(a); a.click(); document.body.removeChild(a); }} title="Download as Playwright test">Playwright <ArrowUpRight size={15} /></button>
                  <button className="card-run card-delete" onClick={() => onRequestDelete(skill)} title="Delete skill">Delete <Trash2 size={14} /></button>
                </span>
              </div>
            ))}
          </div>
        )}
    </section>
  );
}
