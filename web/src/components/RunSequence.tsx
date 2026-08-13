import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import type { Critique } from '../lib/types';
import { PixelProgress } from './PixelProgress';
import { ThinkingTerminal } from './ThinkingTerminal';
import styles from './RunSequence.module.css';

/** 8x8 pixel-art sprites, one per agent. Rendered as box-shadows — zero assets. */
const SPRITES: Record<string, string[]> = {
  user_advocate: [
    '..XXXX..',
    '.XXXXXX.',
    '.XX..XX.',
    '.XXXXXX.',
    '..XXXX..',
    '..X..X..',
    '.XX..XX.',
    '........',
  ],
  engineering: [
    '..XXXX..',
    '.XX..XX.',
    'XX.XX.XX',
    'XX.XX.XX',
    'XX.XX.XX',
    '.XX..XX.',
    '..XXXX..',
    '........',
  ],
  business: [
    '..XXXX..',
    '.XXXXXX.',
    'XX.XX.XX',
    'XX.XX.XX',
    'XX.XX.XX',
    'XX.XX.XX',
    '.XXXXXX.',
    '..XXXX..',
  ],
  design: [
    '......XX',
    '.....XX.',
    '....XX..',
    '...XX...',
    '..XX....',
    '.XX.....',
    'XX....XX',
    'XXXXXXXX',
  ],
  supervisor: [
    '..XXXX..',
    '.XXXXXX.',
    'XX.XX.XX',
    'X.XXXX.X',
    'X.XXXX.X',
    'XX.XX.XX',
    '.XXXXXX.',
    '..XXXX..',
  ],
};

const CRITIC_COLORS: Record<string, string> = {
  user_advocate: '#6ea8ff',
  engineering: '#8bff5f',
  business: '#ffc94d',
  design: '#ff5fc8',
  supervisor: '#e8e8ea',
};

const PX = 2; // rendered pixel size in px

function spriteStyle(name: string): CSSProperties {
  const art = SPRITES[name] ?? SPRITES.supervisor;
  const color = CRITIC_COLORS[name] ?? '#e8e8ea';
  const shadows: string[] = [];
  art.forEach((row, y) => {
    [...row].forEach((ch, x) => {
      if (ch === 'X') shadows.push(`${x * PX}px ${y * PX}px 0 ${color}`);
    });
  });
  return { boxShadow: shadows.join(',') };
}

interface AgentRow {
  id: string;
  label: string;
  sprite: string;
  status: 'idle' | 'active' | 'done';
  findings: number;
}

interface Props {
  /** 0..5 — mirrors the stage counter in ReviewPage */
  stage: number;
  stageLabel: string;
  critiques: Critique[];
  rounds: number;
  converged: boolean;
  /** Battle-log lines, newest last */
  log: string[];
  thinkingText: string;
  thinkingDone: boolean;
}

const SCAN_LINES = [
  '扫描依赖清单…',
  '核对 SKILL 库匹配…',
  '逐条 claim 交叉审阅…',
  '标记证据行号…',
  '收敛判定准备中…',
];

/**
 * The "waiting room" of a run — an 8-bit battle log:
 * four critic sprites scanning the PRD, a boot-sequence log driven by real
 * pipeline events, and the supervisor's live reasoning in a terminal window.
 */
export function RunSequence({
  stage,
  stageLabel,
  critiques,
  rounds,
  converged,
  log,
  thinkingText,
  thinkingDone,
}: Props) {
  const [scanLineIdx, setScanLineIdx] = useState(0);

  // While the graph phase runs (stage 1), cycle decorative scan lines so the
  // 30s LLM stretch stays alive — these describe the pipeline generically,
  // they never fabricate results.
  useEffect(() => {
    if (stage !== 1) return;
    const timer = setInterval(() => {
      setScanLineIdx((i) => (i + 1) % SCAN_LINES.length);
    }, 3200);
    return () => clearInterval(timer);
  }, [stage]);

  const counts = useMemo(() => {
    const map: Record<string, number> = {};
    for (const c of critiques) map[c.critic_id] = (map[c.critic_id] ?? 0) + 1;
    return map;
  }, [critiques]);

  const rows: AgentRow[] = [
    {
      id: 'user_advocate',
      label: 'User Advocate',
      sprite: 'user_advocate',
      status: stage >= 2 ? 'done' : stage >= 1 ? 'active' : 'idle',
      findings: counts.user_advocate ?? 0,
    },
    {
      id: 'engineering',
      label: 'Engineering',
      sprite: 'engineering',
      status: stage >= 2 ? 'done' : stage >= 1 ? 'active' : 'idle',
      findings: counts.engineering ?? 0,
    },
    {
      id: 'business',
      label: 'Business',
      sprite: 'business',
      status: stage >= 2 ? 'done' : stage >= 1 ? 'active' : 'idle',
      findings: counts.business ?? 0,
    },
    {
      id: 'design',
      label: 'Design',
      sprite: 'design',
      status: stage >= 2 ? 'done' : stage >= 1 ? 'active' : 'idle',
      findings: counts.design ?? 0,
    },
  ];

  const supervisorRow: AgentRow = {
    id: 'supervisor',
    label: 'Supervisor',
    sprite: 'supervisor',
    status: stage >= 4 ? 'active' : 'idle',
    findings: 0,
  };

  return (
    <div className={styles.deck} role="status" aria-live="polite">
      <div className={styles.topline}>
        <span className={styles.deckTitle}>评审擂台</span>
        <PixelProgress total={5} filled={Math.max(stage, 1)} label={stageLabel} active />
      </div>

      <div className={styles.arena}>
        <div className={styles.squad}>
          {rows.map((row) => (
            <div
              key={row.id}
              className={`${styles.agentRow} ${styles[row.status]}`}
            >
              <span className={styles.spriteWrap} aria-hidden>
                <span className={styles.sprite} style={spriteStyle(row.sprite)} />
              </span>
              <span className={styles.agentName}>{row.label}</span>
              <span className={styles.agentState}>
                {row.status === 'active' && (
                  <>
                    <span className={styles.scanGlyph}>▚</span>
                    <span className={styles.scanText}>{SCAN_LINES[scanLineIdx]}</span>
                  </>
                )}
                {row.status === 'done' && (
                  <span className={styles.doneState}>READY ×{row.findings}</span>
                )}
                {row.status === 'idle' && <span className={styles.idleState}>待命</span>}
              </span>
            </div>
          ))}
        </div>

        <div className={`${styles.squad} ${styles.supervisorRow}`}>
          <div
            className={`${styles.agentRow} ${styles[supervisorRow.status]}`}
          >
            <span className={styles.spriteWrap} aria-hidden>
              <span className={styles.sprite} style={spriteStyle('supervisor')} />
            </span>
            <span className={styles.agentName}>Supervisor</span>
            <span className={styles.agentState}>
              {supervisorRow.status === 'active' && (
                <span className={styles.scanText}>推理中<span className="px-cursor" aria-hidden /></span>
              )}
              {supervisorRow.status === 'idle' && <span className={styles.idleState}>等待裁决</span>}
            </span>
          </div>
        </div>
      </div>

      <div className={styles.log}>
        {log.map((line, i) => (
          <div key={i} className={`px-mono ${styles.logLine} ${i === log.length - 1 ? styles.logLast : ''}`}>
            <span className={styles.logPrompt}>▸</span>
            {line}
            {i === log.length - 1 && !thinkingDone && (
              <span className="px-cursor" aria-hidden />
            )}
          </div>
        ))}
      </div>

      {(stage >= 4 || thinkingText) && (
        <div className={styles.supervisorWin}>
          <div className={styles.winBar}>
            <span className={styles.winTitle}>SUPERVISOR.SYS</span>
            <span className={styles.winBtns} aria-hidden>
              <i>_</i>
              <i>□</i>
              <i>×</i>
            </span>
          </div>
          <ThinkingTerminal
            text={thinkingText}
            inProgress={!thinkingDone}
            label={converged ? `推理 · 第 ${rounds} 轮收敛` : '推理'}
          />
        </div>
      )}
    </div>
  );
}
