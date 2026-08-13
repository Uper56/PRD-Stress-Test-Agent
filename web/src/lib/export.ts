/** Markdown report builder + file download — the export path for verdicts.

   .md is the primary export: zero dependencies, instant, pastes cleanly
   into docs/飞书/Notion. Printing to PDF stays available via the browser
   (see the print stylesheet in styles/base.css).
*/

import type { Critique, Verdict } from './types';

export interface ReportInput {
  prdFilename?: string | null;
  timestamp?: string;
  verdict: Verdict;
  critiques: Critique[];
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const CRITIC_NAMES: Record<string, string> = {
  user_advocate: 'User Advocate',
  engineering: 'Engineering',
  business: 'Business',
  design: 'Design',
};

export function buildMarkdownReport({
  prdFilename,
  timestamp,
  verdict,
  critiques,
  t,
}: ReportInput): string {
  const lines: string[] = [];
  const title = prdFilename && prdFilename !== '' ? prdFilename : t('history.custom');
  lines.push(`# ${t('export.title')} — ${title}`);
  if (timestamp) lines.push(`\n> ${timestamp}`);
  lines.push(`\n## ${t('export.subtitle')}\n`);

  if (verdict.executive_summary) {
    lines.push(`**${t('export.executive')}：** ${verdict.executive_summary}\n`);
  }

  const groups: [string, string[]][] = [
    ['P0', verdict.p0_blockers ?? []],
    ['P1', verdict.p1_concerns ?? []],
    ['P2', verdict.p2_suggestions ?? []],
  ];
  for (const [sev, items] of groups) {
    if (!items.length) continue;
    lines.push(`### ${sev}`);
    for (const item of items) lines.push(`- ${item}`);
    lines.push('');
  }

  if ((verdict.conflict_resolutions ?? []).length > 0) {
    lines.push(`## ${t('export.conflicts')}\n`);
    for (const c of verdict.conflict_resolutions ?? []) lines.push(`- ${c}`);
    lines.push('');
  }

  lines.push(`## ${t('export.findings')}\n`);
  for (const c of critiques) {
    const name = CRITIC_NAMES[c.critic_id] ?? c.critic_id;
    lines.push(`### [${c.severity ?? '?'}] ${name} — ${c.finding}`);
    if (c.claim_id) lines.push(`\n- claim: \`${c.claim_id}\``);
    if (c.evidence) lines.push(`- ${t('export.evidence')}：${c.evidence}`);
    if (c.suggested_fix) lines.push(`- ${t('export.fix')}：${c.suggested_fix}`);
    if (c.skill_id) lines.push(`- Skill: \`${c.skill_id}\``);
    lines.push('');
  }

  lines.push(`\n---\n*${t('export.generated')} · ${new Date().toISOString().slice(0, 10)}*`);
  return lines.join('\n');
}

export function downloadFile(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: `${mime};charset=utf-8` });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
