import { describe, expect, it } from 'vitest';
import { buildMarkdownReport } from './export';
import type { Critique, Verdict } from './types';

const zhT = (key: string, vars?: Record<string, string | number>) => {
  const dict: Record<string, string> = {
    'export.title': 'PRD 评审报告',
    'export.subtitle': 'Supervisor 裁决',
    'export.executive': '核心结论',
    'export.conflicts': '分歧裁决',
    'export.findings': 'Critic 发现',
    'export.evidence': '原文依据',
    'export.fix': '建议改进',
    'export.generated': '由 PIXEL·PRD 生成',
    'history.custom': '自定义 PRD',
  };
  let s = dict[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) s = s.replaceAll(`{${k}}`, String(v));
  return s;
};

const verdict: Verdict = {
  executive_summary: 'One P0 blocker on metric quality.',
  p0_blockers: ['Success metric lacks baseline.'],
  p1_concerns: ['No rate-limit strategy.'],
  p2_suggestions: [],
  conflict_resolutions: ['ua challenged biz:C-002 — keep P0'],
};

const critiques: Critique[] = [
  {
    critic_id: 'business',
    severity: 'P0',
    finding: 'Success metric lacks baseline.',
    evidence: 'line 2: "Deflect 40% of inbound tickets."',
    suggested_fix: 'Add a baseline.',
    claim_id: 'C-002',
  },
];

describe('buildMarkdownReport', () => {
  it('renders verdict sections and preserves evidence quotes', () => {
    const md = buildMarkdownReport({
      prdFilename: 'prd_001.md',
      timestamp: '2026-08-13T00:00:00Z',
      verdict,
      critiques,
      t: zhT,
    });
    expect(md).toContain('PRD 评审报告');
    expect(md).toContain('### P0');
    expect(md).toContain('Success metric lacks baseline.');
    // Evidence quote preserved verbatim
    expect(md).toContain('Deflect 40% of inbound tickets.');
    expect(md).toContain('### [P0] Business');
    expect(md).toContain('分歧裁决');
  });

  it('falls back to a custom-PRD title when no filename given', () => {
    const md = buildMarkdownReport({
      prdFilename: null,
      verdict: { executive_summary: 'ok' },
      critiques: [],
      t: zhT,
    });
    expect(md).toContain('自定义 PRD');
  });
});
