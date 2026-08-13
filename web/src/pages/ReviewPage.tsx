import { useCallback, useState } from 'react';
import { Composer, type ComposerPayload } from '../components/Composer';
import { CritiqueCard, type FeedbackState } from '../components/CritiqueCard';
import { HistoryRail } from '../components/HistoryRail';
import { PixelProgress } from '../components/PixelProgress';
import { ThinkingTerminal } from '../components/ThinkingTerminal';
import { VerdictPanel } from '../components/VerdictPanel';
import { api, ApiError } from '../lib/api';
import type { Challenge, Critique, HistoryDetail, Verdict } from '../lib/types';
import { useSSE } from '../lib/useSSE';
import styles from './ReviewPage.module.css';

const CRITIC_TABS: [string, string][] = [
  ['user_advocate', 'User Advocate'],
  ['engineering', 'Engineering'],
  ['business', 'Business'],
  ['design', 'Design'],
];

const STAGE_LABELS: Record<number, string> = {
  1: 'Intake · 抽取 claim',
  2: '4 个 Critic 评审中',
  3: '智能体互辩',
  4: 'Supervisor 裁决中',
  5: '完成',
};

/** The review workspace — composer in, streamed verdict out. */
export function ReviewPage() {
  const [runId, setRunId] = useState<string | null>(null);
  const [streamUrl, setStreamUrl] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [stage, setStage] = useState(0);
  const [thinkingText, setThinkingText] = useState('');
  const [thinkingDone, setThinkingDone] = useState(false);
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [critiques, setCritiques] = useState<Critique[]>([]);
  const [challenges, setChallenges] = useState<Challenge[]>([]);
  const [rounds, setRounds] = useState(0);
  const [converged, setConverged] = useState(false);
  const [quotaError, setQuotaError] = useState<string | null>(null);
  const [reconnecting, setReconnecting] = useState(false);
  const [feedback, setFeedback] = useState<Record<string, FeedbackState>>({});
  const [historyDetail, setHistoryDetail] = useState<HistoryDetail | null>(null);
  const [historyTick, setHistoryTick] = useState(0);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [liveCriticTab, setLiveCriticTab] = useState(0);

  const handleRun = useCallback(async (payload: ComposerPayload) => {
    setQuotaError(null);
    setHistoryDetail(null);
    setHistoryError(null);
    setRunId(null);
    setStreamUrl(null);
    setStage(0);
    setThinkingText('');
    setThinkingDone(false);
    setVerdict(null);
    setCritiques([]);
    setChallenges([]);
    setFeedback({});
    try {
      const res = await api.startReview(payload.prdText, payload.prdFilename);
      setRunId(res.run_id);
      setStreamUrl(res.stream_url);
      setRunning(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const d = err.detail as { reason?: string } | undefined;
        setQuotaError(
          d?.reason === 'global'
            ? '🛑 今日 demo 额度已用尽，请明天再试。'
            : '⏳ 本 IP 本小时已达上限，请稍后再试。',
        );
      } else {
        setQuotaError(err instanceof Error ? err.message : '启动评审失败');
      }
    }
  }, []);

  useSSE(streamUrl, {
    onEvent: (ev) => {
      setReconnecting(false);
      switch (ev.event) {
        case 'phase': {
          const name = String(ev.data.name ?? '');
          if (name === 'graph') setStage(1);
          if (name === 'supervisor') setStage(4);
          break;
        }
        case 'critiques':
          setCritiques((ev.data.critiques as Critique[]) ?? []);
          setStage(2);
          break;
        case 'challenges':
          setChallenges((ev.data.challenges as Challenge[]) ?? []);
          setRounds(Number(ev.data.rounds ?? 0));
          setConverged(Boolean(ev.data.converged));
          setStage(3);
          break;
        case 'thinking':
          setThinkingText((t) => t + String(ev.data.delta ?? ''));
          break;
        case 'verdict':
          setVerdict((ev.data.verdict as Verdict) ?? null);
          break;
        case 'done':
          setVerdict((ev.data.verdict as Verdict) ?? null);
          setStage(5);
          setRunning(false);
          setThinkingDone(true);
          setHistoryTick((t) => t + 1);
          break;
        case 'error': {
          const message = String(ev.data.message ?? '评审失败');
          if (message.includes('历史记录保存失败')) break; // non-fatal
          setQuotaError(message);
          setRunning(false);
          setStage(0);
          break;
        }
      }
    },
    onError: () => setReconnecting(true),
    onClose: () => {
      setRunning(false);
    },
    reconnectMs: 3000,
  });

  const handleHistorySelect = useCallback(async (id: string) => {
    try {
      const detail = await api.historyDetail(id);
      setHistoryDetail(detail);
      setHistoryError(null);
      setLiveCriticTab(0);
    } catch {
      setHistoryError('无法加载这份历史评审');
    }
  }, []);

  const handleFeedback = useCallback(
    async (skillId: string, uid: string, accepted: boolean) => {
      try {
        await api.skillFeedback(skillId, accepted);
        setFeedback((m) => ({ ...m, [uid]: accepted ? 'accepted' : 'rejected' }));
      } catch {
        /* feedback is best-effort — old UI treated it the same way */
      }
    },
    [],
  );

  // History view renders the persisted record; live view renders the stream.
  const historyCritiqueKey = (c: Critique) =>
    `${c.critic_id}|${c.claim_id}|${c.finding}`;

  const activeCritiques = historyDetail ? historyDetail.critiques : critiques;
  const activeVerdict = historyDetail ? historyDetail.supervisor_verdict : verdict;
  const activeChallenges = historyDetail
    ? (historyDetail.challenges ?? [])
    : challenges;
  const activeConverged = historyDetail ? true : converged;
  const activeRounds = historyDetail ? 0 : rounds;
  const discussUrl = runId && !historyDetail ? `/api/reviews/${runId}/discuss` : null;
  const resultsReady =
    historyDetail !== null || (!running && (verdict !== null || critiques.length > 0));

  return (
    <div className={styles.layout}>
      <aside className={styles.side}>
        <HistoryRail
          key={historyTick}
          selectedId={historyDetail?.run_id ?? null}
          onSelect={(id) => void handleHistorySelect(id)}
        />
      </aside>

      <div className={styles.workspace}>
        <div className={styles.hero}>
          <div className={styles.kicker}>评审工作台</div>
          <h1 className={styles.heroTitle}>把 PRD 放进来，先看风险，再看证据。</h1>
          <p className={styles.heroHint}>支持粘贴内容、选择示例或上传 PDF / Word 文档。</p>
        </div>

        {historyError && <div className={styles.bannerErr}>{historyError}</div>}
        {reconnecting && running && (
          <div className={styles.banner}>📡 信号丢失 · 正在重连…</div>
        )}

        <Composer onRun={(p) => void handleRun(p)} quotaError={quotaError} running={running} />

        {running && (
          <div className={styles.progressZone}>
            <PixelProgress
              total={5}
              filled={Math.max(stage, 1)}
              label={STAGE_LABELS[Math.max(stage, 1)]}
              active
            />
            <ThinkingTerminal text={thinkingText} inProgress={!thinkingDone} />
          </div>
        )}

        {resultsReady && (
          <RunResultsView
            critiques={activeCritiques}
            challenges={activeChallenges}
            rounds={activeRounds}
            converged={activeConverged}
            verdict={activeVerdict}
            thinkingText={historyDetail ? '' : thinkingText}
            discussUrl={discussUrl}
            feedback={feedback}
            onFeedback={handleFeedback}
            liveCriticTab={liveCriticTab}
            setLiveCriticTab={setLiveCriticTab}
            historyCritiqueKey={historyCritiqueKey}
          />
        )}
      </div>
    </div>
  );
}

interface ResultsProps {
  critiques: Critique[];
  challenges: Challenge[];
  rounds: number;
  converged: boolean;
  verdict: Verdict | null;
  thinkingText: string;
  discussUrl: string | null;
  feedback: Record<string, FeedbackState>;
  onFeedback: (skillId: string, uid: string, accepted: boolean) => void;
  liveCriticTab: number;
  setLiveCriticTab: (i: number) => void;
  historyCritiqueKey: (c: Critique) => string;
}

function RunResultsView(props: ResultsProps) {
  const {
    critiques,
    challenges,
    rounds,
    converged,
    verdict,
    thinkingText,
    discussUrl,
    feedback,
    onFeedback,
    liveCriticTab,
    setLiveCriticTab,
    historyCritiqueKey,
  } = props;

  const byCritic: Record<string, Critique[]> = {};
  for (const c of critiques) (byCritic[c.critic_id] ??= []).push(c);

  const byRound: Record<number, Challenge[]> = {};
  for (const ch of challenges) (byRound[Number(ch.round ?? 0)] ??= []).push(ch);

  return (
    <div className={styles.results}>
      {verdict && <VerdictPanel verdict={verdict} />}

      {thinkingText && (
        <details className={styles.thinkingWrap}>
          <summary className={styles.thinkingSummary}>推理（完成）</summary>
          <ThinkingTerminal text={thinkingText} inProgress={false} label="推理过程" />
        </details>
      )}

      <section>
        <h2 className={styles.sectionHead}>
          Critic 评审结果 <span className={styles.sectionCount}>{critiques.length}</span>
        </h2>
        <div className={styles.tabs} role="tablist">
          {CRITIC_TABS.map(([key, label], i) => (
            <button
              key={key}
              role="tab"
              aria-selected={liveCriticTab === i}
              className={`${styles.tab} ${liveCriticTab === i ? styles.tabActive : ''}`}
              onClick={() => setLiveCriticTab(i)}
            >
              {label}
              <em className={styles.tabCount}>{byCritic[key]?.length ?? 0}</em>
            </button>
          ))}
        </div>
        <div className={styles.cards}>
          {(byCritic[CRITIC_TABS[liveCriticTab][0]] ?? []).map((c) => {
            const uid = c.uid ?? historyCritiqueKey(c);
            return (
              <CritiqueCard
                key={uid}
                critique={c}
                discussUrl={discussUrl}
                feedback={feedback[uid] ?? null}
                onFeedback={
                  c.skill_id
                    ? (accepted) => onFeedback(c.skill_id!, uid, accepted)
                    : undefined
                }
              />
            );
          })}
          {(byCritic[CRITIC_TABS[liveCriticTab][0]] ?? []).length === 0 && (
            <div className={styles.noFindings}>此 Critic 暂无发现</div>
          )}
        </div>
      </section>

      {challenges.length > 0 && (
        <details className={styles.crossWrap}>
          <summary className={styles.crossSummary}>
            🔀 智能体互辩 · {challenges.length} 条记录
          </summary>
          <div className={styles.crossBody}>
            {converged ? (
              <div className={styles.crossOk}>✅ 第 {rounds} 轮收敛</div>
            ) : (
              <div className={styles.crossWarn}>⚠️ 达到最大轮数（{rounds}）仍未收敛</div>
            )}
            {Object.keys(byRound)
              .sort((a, b) => Number(a) - Number(b))
              .map((rn) => (
                <div key={rn} className={styles.crossRound}>
                  <div className={`px-label ${styles.crossRoundHead}`}>
                    第 {rn} 轮 —— {byRound[Number(rn)].length} 条互辩
                  </div>
                  {byRound[Number(rn)].map((ch, i) => (
                    <div key={i} className={styles.crossItem}>
                      <span className="px-mono">
                        {String(ch.challenger ?? '?')} → {String(ch.target_critique_id ?? '?')}
                      </span>
                      <div className={styles.crossCounter}>
                        {String(ch.counter_finding ?? '')}
                      </div>
                    </div>
                  ))}
                </div>
              ))}
          </div>
        </details>
      )}
    </div>
  );
}
