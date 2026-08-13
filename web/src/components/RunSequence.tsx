import { useEffect, useMemo, useState } from 'react';
import type { CSSProperties } from 'react';
import { useT } from '../lib/i18n';
import type { Critique } from '../lib/types';
import { PixelButton } from './PixelButton';
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
  trophy: [
    '...XX...',
    '..XXXX..',
    '..XXXX..',
    '.X.XX.X.',
    '..XXXX..',
    '...XX...',
    '..XXXX..',
    '.XXXXXX.',
  ],
};

const CRITIC_COLORS: Record<string, string> = {
  user_advocate: '#6ea8ff',
  engineering: '#8bff5f',
  business: '#ffc94d',
  design: '#ff5fc8',
  supervisor: '#e8e8ea',
  trophy: '#ffc94d',
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
  /** 0..5 — the real pipeline stage (driven by SSE events) */
  stage: number;
  critiques: Critique[];
  rounds: number;
  converged: boolean;
  /** Battle-log lines, newest last */
  log: string[];
  thinkingText: string;
  thinkingDone: boolean;
  /** Called when the user clicks「查看结果」after the CLEAR! beat */
  onViewResults: () => void;
}

/** ms per progress-block — the bar walks up to the real stage, one pixel
 *  block at a time, instead of teleporting when events burst in. */
const BLOCK_STEP_MS = 300;

/**
 * The "waiting room" of a run — an 8-bit battle log:
 * four critic sprites scanning the PRD, a boot-sequence log driven by real
 * pipeline events, and the supervisor's live reasoning in a terminal window.
 */
export function RunSequence({
  stage,
  critiques,
  rounds,
  converged,
  log,
  thinkingText,
  thinkingDone,
  onViewResults,
}: Props) {
  const { t } = useT();
  const [scanLineIdx, setScanLineIdx] = useState(0);
  // Display stage lags the real stage by BLOCK_STEP_MS per block — events
  // burst (critiques → challenges → supervisor within ~1s), but the bar
  // should still fill progressively.
  const [displayStage, setDisplayStage] = useState(0);
  // The「查看结果」button appears only after the CLEAR! beat has played out.
  const [showViewButton, setShowViewButton] = useState(false);

  const stageLabels: Record<number, string> = {
    0: t('deck.submitting'),
    1: t('deck.stage1'),
    2: t('deck.stage2'),
    3: t('deck.stage3'),
    4: t('deck.stage4'),
    5: t('deck.stage5'),
  };

  const scanLines = [
    t('deck.scan1'),
    t('deck.scan2'),
    t('deck.scan3'),
    t('deck.scan4'),
    t('deck.scan5'),
  ];

  useEffect(() => {
    if (stage <= displayStage) {
      setDisplayStage(stage); // snap back on reset / error
      return;
    }
    const timer = setTimeout(
      () => setDisplayStage((d) => Math.min(d + 1, stage)),
      BLOCK_STEP_MS,
    );
    return () => clearTimeout(timer);
  }, [stage, displayStage]);

  useEffect(() => {
    if (displayStage < 5) {
      setShowViewButton(false);
      return;
    }
    const timer = setTimeout(() => setShowViewButton(true), 1400);
    return () => clearTimeout(timer);
  }, [displayStage]);

  // While the graph phase runs (display stage 1), cycle decorative scan
  // lines so the 30s LLM stretch stays alive — these describe the pipeline
  // generically, they never fabricate results.
  useEffect(() => {
    if (displayStage !== 1) return;
    const timer = setInterval(() => {
      setScanLineIdx((i) => (i + 1) % scanLines.length);
    }, 3200);
    return () => clearInterval(timer);
  }, [displayStage, scanLines.length]);

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
      status: displayStage >= 2 ? 'done' : displayStage >= 1 ? 'active' : 'idle',
      findings: counts.user_advocate ?? 0,
    },
    {
      id: 'engineering',
      label: 'Engineering',
      sprite: 'engineering',
      status: displayStage >= 2 ? 'done' : displayStage >= 1 ? 'active' : 'idle',
      findings: counts.engineering ?? 0,
    },
    {
      id: 'business',
      label: 'Business',
      sprite: 'business',
      status: displayStage >= 2 ? 'done' : displayStage >= 1 ? 'active' : 'idle',
      findings: counts.business ?? 0,
    },
    {
      id: 'design',
      label: 'Design',
      sprite: 'design',
      status: displayStage >= 2 ? 'done' : displayStage >= 1 ? 'active' : 'idle',
      findings: counts.design ?? 0,
    },
  ];

  const supervisorRow: AgentRow = {
    id: 'supervisor',
    label: 'Supervisor',
    sprite: 'supervisor',
    status:
      displayStage >= 5 ? 'done' : displayStage >= 4 ? 'active' : 'idle',
    findings: 0,
  };

  const cleared = displayStage >= 5;
  const confetti = ['#ff5fc8', '#8bff5f', '#ffc94d', '#6ea8ff', '#ff6b5e', '#e8e8ea'];

  return (
    <div className={`${styles.deck} ${cleared ? styles.deckCleared : ''}`} role="status" aria-live="polite">
      {cleared && (
        <div className={styles.clearBanner} aria-hidden>
          <span className={styles.trophyWrap}>
            <span className={styles.trophy} style={spriteStyle('trophy')} />
          </span>
          <span className={styles.clearText}>CLEAR!</span>
          <span className={styles.clearSub}>{t('deck.clear')}</span>
          {confetti.map((color, i) => (
            <span
              key={i}
              className={styles.confetti}
              style={{
                background: color,
                left: `${14 + i * 13}%`,
                animationDelay: `${i * 45}ms`,
              }}
            />
          ))}
        </div>
      )}
      <div className={styles.topline}>
        <span className={styles.deckTitle}>{t('deck.title')}</span>
        <PixelProgress
          total={5}
          filled={displayStage}
          label={stageLabels[displayStage] ?? ''}
          active
        />
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
                    <span className={styles.scanText}>{scanLines[scanLineIdx]}</span>
                  </>
                )}
                {row.status === 'done' && (
                  <span className={styles.doneState}>READY ×{row.findings}</span>
                )}
                {row.status === 'idle' && (
                  <span className={styles.idleState}>{t('deck.idle')}</span>
                )}
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
                <span className={styles.scanText}>
                  {t('deck.reasoning')}
                  <span className="px-cursor" aria-hidden />
                </span>
              )}
              {supervisorRow.status === 'done' && (
                <span className={styles.doneState}>{t('deck.verdictDone')}</span>
              )}
              {supervisorRow.status === 'idle' && (
                <span className={styles.idleState}>{t('deck.awaitingVerdict')}</span>
              )}
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

      {(displayStage >= 4 || thinkingText) && (
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
            label={converged ? t('deck.reasoningConverged', { r: rounds }) : t('deck.reasoningLabel')}
          />
        </div>
      )}

      {cleared && showViewButton && (
        <div className={styles.viewBar}>
          <PixelButton variant="primary" onClick={onViewResults}>
            {t('deck.viewResults')}
          </PixelButton>
        </div>
      )}
    </div>
  );
}
