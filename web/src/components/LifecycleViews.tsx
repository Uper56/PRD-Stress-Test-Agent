import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type {
  GateReportT,
  LibraryRow,
  LifecycleLineage,
  LifecycleOverview,
  SkillStatus,
} from '../lib/types';
import { EmptyState } from './EmptyState';
import { PixelButton } from './PixelButton';
import styles from './LifecycleViews.module.css';

/* Skill Lifecycle Center views — Overview and Library.
 *
 * Per the product review: the pixel shell stays as brand chrome, but the
 * governance surfaces (tables, audit rows, gate reports) use restrained
 * Inter/monospace typography and quiet controls — evidence first, no
 * game-like decoration. */

const STATUS_CLASS: Record<SkillStatus, string> = {
  candidate: 'st-candidate',
  approved: 'st-approved',
  active: 'st-active',
  degraded: 'st-degraded',
  deprecated: 'st-deprecated',
  rejected: 'st-rejected',
};

const pct = (v: number | null) =>
  v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`;

export function StatusChip({ status }: { status: SkillStatus | string }) {
  return (
    <span className={`${styles.chip} ${STATUS_CLASS[status as SkillStatus] ?? ''}`}>
      {status}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

export function OverviewView({ onChanged }: { onChanged: () => void }) {
  const { t } = useT();
  const [data, setData] = useState<LifecycleOverview | null>(null);

  useEffect(() => {
    api.lifecycleOverview().then(setData).catch(() => setData(null));
  }, []);

  if (!data) {
    return <EmptyState glyph="▚▚" title={t('lc.overview.empty')} />;
  }

  const counts = data.counts ?? {};
  const cards = [
    { label: t('lc.count.total'), value: data.total_skills, cls: '' },
    { label: t('lc.count.active'), value: counts.active ?? 0, cls: 'cx-active' },
    { label: t('lc.count.degraded'), value: counts.degraded ?? 0, cls: 'cx-degraded' },
    { label: t('lc.count.deprecated'), value: counts.deprecated ?? 0, cls: 'cx-deprecated' },
  ];

  return (
    <div className={styles.overview}>
      <div className={styles.cards}>
        {cards.map((c) => (
          <div key={c.label} className={`${styles.card} ${c.cls}`}>
            <div className={styles.cardNum}>{c.value}</div>
            <div className={styles.cardLabel}>{c.label}</div>
          </div>
        ))}
      </div>

      <section className={styles.panel}>
        <h2 className={styles.panelTitle}>{t('lc.degraded.heading')}</h2>
        {data.degraded.length === 0 ? (
          <p className={styles.muted}>{t('lc.degraded.none')}</p>
        ) : (
          <ul className={styles.degradedList}>
            {data.degraded.map((d) => (
              <li key={d.skill_name} className={styles.degradedRow}>
                <div className={styles.degradedMain}>
                  <span className="px-mono">{d.skill_name}</span>
                  <span className={styles.muted}> — {d.reason}</span>
                  {d.rollback_target && (
                    <span className={styles.rollbackHint}>↩ {d.rollback_target}</span>
                  )}
                </div>
                <div className={styles.degradedSide}>
                  <span className={styles.muted}>
                    {t('lc.degraded.since', { t: d.since.slice(0, 16).replace('T', ' ') })}
                  </span>
                  <RollbackButton name={d.skill_name} onChanged={onChanged} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className={styles.panel}>
        <h2 className={styles.panelTitle}>{t('lc.queue.heading')}</h2>
        {data.intervention_queue.length === 0 ? (
          <p className={styles.muted}>{t('lc.queue.none')}</p>
        ) : (
          <table className={styles.table}>
            <tbody>
              {data.intervention_queue.map((q) => (
                <tr key={q.skill_name}>
                  <td className="px-mono">{q.skill_name}</td>
                  <td className={styles.muted}>
                    {t('lc.queue.probation', { t: q.triggers, n: q.feedback_samples })}
                  </td>
                  <td>
                    {q.recent_acceptance === null
                      ? t('lc.queue.noRate')
                      : t('lc.queue.rate', { r: pct(q.recent_acceptance) })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className={styles.panel}>
        <h2 className={styles.panelTitle}>{t('lc.recent.heading')}</h2>
        {data.recent_admissions.length === 0 ? (
          <p className={styles.muted}>{t('lc.recent.none')}</p>
        ) : (
          <table className={styles.table}>
            <tbody>
              {data.recent_admissions.map((r, i) => (
                <tr key={`${r.skill_name}-${r.at}-${i}`}>
                  <td className={styles.muted}>{r.at.slice(0, 16).replace('T', ' ')}</td>
                  <td className="px-mono">{r.skill_name}</td>
                  <td>
                    <StatusChip status={r.to_status} />
                  </td>
                  <td className={styles.muted}>{r.actor ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

function RollbackButton({ name, onChanged }: { name: string; onChanged: () => void }) {
  const { t } = useT();
  const [busy, setBusy] = useState(false);
  return (
    <PixelButton
      size="sm"
      disabled={busy}
      onClick={() => {
        setBusy(true);
        api
          .lifecycleRollback(name)
          .then(onChanged)
          .catch(() => setBusy(false));
      }}
    >
      {busy ? '…' : t('lc.actions.rollback')}
    </PixelButton>
  );
}

// ---------------------------------------------------------------------------
// Library
// ---------------------------------------------------------------------------

export function LibraryView({ onChanged }: { onChanged: () => void }) {
  const { t } = useT();
  const [rows, setRows] = useState<LibraryRow[] | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(() => {
    api.lifecycleLibrary().then(setRows).catch(() => setRows([]));
  }, []);
  useEffect(load, [load]);

  if (rows === null) return <p className={styles.muted}>…</p>;
  if (rows.length === 0) {
    return <EmptyState glyph="▚▚" title={t('lc.library.empty')} />;
  }

  const act = async (fn: () => Promise<unknown>) => {
    await fn();
    load();
    onChanged();
  };

  return (
    <div className={styles.libraryWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>{t('lc.row.skill')}</th>
            <th>{t('lc.row.version')}</th>
            <th>{t('lc.row.status')}</th>
            <th>{t('lc.row.usage')}</th>
            <th>{t('lc.row.applied')}</th>
            <th>{t('lc.row.acceptance')}</th>
            <th>{t('lc.row.source')}</th>
            <th>{t('lc.row.actions')}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <LibraryRowView
              key={row.skill_name}
              row={row}
              expanded={expanded === row.skill_name}
              onToggle={() =>
                setExpanded((cur) => (cur === row.skill_name ? null : row.skill_name))
              }
              onAct={act}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LibraryRowView({
  row,
  expanded,
  onToggle,
  onAct,
}: {
  row: LibraryRow;
  expanded: boolean;
  onToggle: () => void;
  onAct: (fn: () => Promise<unknown>) => Promise<void>;
}) {
  const { t } = useT();
  const [md, setMd] = useState<string | null>(null);
  const [showMd, setShowMd] = useState(false);

  const src = row.source;
  const sourceLabel = !src
    ? '—'
    : src.created_by === 'seed'
      ? t('lc.source.seed')
      : t('lc.source.learned', { n: src.prd_count });

  const toggleMd = () => {
    if (showMd) {
      setShowMd(false);
      return;
    }
    setShowMd(true);
    if (md === null) {
      api
        .skillMd(row.skill_name)
        .then((res) => setMd(res.md))
        .catch(() => setMd(''));
    }
  };

  return (
    <>
      <tr className={expanded || showMd ? styles.rowOpen : undefined}>
        <td className="px-mono">{row.skill_name}</td>
        <td>{row.version}</td>
        <td>
          <StatusChip status={row.status} />
        </td>
        <td>{row.usage_count}</td>
        <td>{row.applied_count}</td>
        <td>
          {pct(row.recent_acceptance)}
          {row.feedback_samples > 0 && (
            <span className={styles.muted}> ·n={row.feedback_samples}</span>
          )}
        </td>
        <td className={styles.muted}>
          {sourceLabel}
          {src?.provenance === 'legacy_import' && (
            <span title={src.provenance}> {t('lc.source.legacy')}</span>
          )}
        </td>
        <td>
          <div className={styles.rowActions}>
            {row.status === 'degraded' && row.rollback_target && (
              <PixelButton
                size="sm"
                onClick={() =>
                  onAct(() => api.lifecycleRollback(row.skill_name))
                }
              >
                {t('lc.actions.rollback')}
              </PixelButton>
            )}
            {row.status === 'active' && (
              <PixelButton
                size="sm"
                variant="danger"
                onClick={() =>
                  onAct(() => api.lifecycleDeprecate(row.skill_name))
                }
              >
                {t('lc.actions.deprecate')}
              </PixelButton>
            )}
            <PixelButton size="sm" onClick={onToggle}>
              {t('lc.actions.lineage')}
            </PixelButton>
            <PixelButton size="sm" onClick={toggleMd}>
              {t('lc.actions.md')}
            </PixelButton>
          </div>
        </td>
      </tr>
      {showMd && (
        <tr className={styles.lineageRow}>
          <td colSpan={8}>
            <pre className={styles.mdView}>
              {md === null ? '…' : md || '—'}
            </pre>
          </td>
        </tr>
      )}
      {expanded && (
        <tr className={styles.lineageRow}>
          <td colSpan={8}>
            <LineageDetail name={row.skill_name} />
          </td>
        </tr>
      )}
    </>
  );
}

function LineageDetail({ name }: { name: string }) {
  const { t } = useT();
  const [data, setData] = useState<LifecycleLineage | null>(null);

  useEffect(() => {
    api.lifecycleLineage(name).then(setData).catch(() => setData(null));
  }, [name]);

  if (!data) return <p className={styles.muted}>…</p>;

  return (
    <div className={styles.lineage}>
      <h3 className={styles.lineageTitle}>{t('lc.lineage.versions')}</h3>
      <table className={styles.table}>
        <tbody>
          {data.versions.map((v) => (
            <tr key={v.lineage_id}>
              <td className="px-mono">v{v.version}</td>
              <td className={styles.muted}>
                {v.admission_decision
                  ? t('lc.lineage.admission', {
                      d: v.admission_decision,
                      a: v.admission_actor ?? '?',
                    })
                  : t('lc.lineage.noAdmission')}
              </td>
              <td className={styles.muted}>
                {v.source_proposal_id
                  ? t('lc.lineage.evidence', {
                      n: v.source_prd_hashes.length,
                      p: v.source_proposal_id.slice(0, 8),
                    })
                  : v.created_by}
              </td>
              <td className={styles.muted}>
                {v.parent_version ? `↩ parent v${v.parent_version}` : ''}
              </td>
              <td className={styles.muted}>{v.provenance}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <h3 className={styles.lineageTitle}>{t('lc.lineage.transitions')}</h3>
      <table className={styles.table}>
        <tbody>
          {data.transitions.map((tr) => (
            <tr key={tr.transition_id}>
              <td className={styles.muted}>{tr.at.slice(0, 19).replace('T', ' ')}</td>
              <td>
                {tr.from_status ?? '∅'} → <strong>{tr.to_status}</strong>
              </td>
              <td className={styles.muted}>{tr.reason ?? ''}</td>
              <td className={styles.muted}>{tr.actor ?? ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gate panel (used inside ProposalCard)
// ---------------------------------------------------------------------------

const GATE_KEYS: Array<GateReportT['gate']> = ['spec', 'evidence', 'novelty', 'shadow'];

export function GatePanel({
  proposalId,
  onGatesChanged,
}: {
  proposalId: string;
  onGatesChanged?: (allPassed: boolean) => void;
}) {
  const { t } = useT();
  const [latest, setLatest] = useState<Record<string, GateReportT>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load existing reports once; refresh after each run.
  useEffect(() => {
    api
      .lifecycleGates(proposalId)
      .then((reports) => {
        const map: Record<string, GateReportT> = {};
        for (const r of reports) if (!map[r.gate]) map[r.gate] = r; // newest first
        setLatest(map);
        onGatesChanged?.(GATE_KEYS.every((g) => map[g]?.passed));
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [proposalId]);

  const run = async (includeShadow: boolean) => {
    setBusy(true);
    setError(null);
    try {
      const res = await api.lifecycleRunGates(proposalId, includeShadow);
      setLatest(res.latest);
      onGatesChanged?.(GATE_KEYS.every((g) => res.latest[g]?.passed));
    } catch (err) {
      setError(err instanceof Error ? err.message : t('proposal.fail'));
    } finally {
      setBusy(false);
    }
  };

  const shadowDetail = latest.shadow?.detail as
    | { metrics_off?: Record<string, number>; metrics_on?: Record<string, number>; gate_reason?: string; target_pattern_hits?: number | null }
    | undefined;

  return (
    <div className={styles.gates}>
      <div className={styles.gatesHead}>
        <span className={styles.gatesTitle}>{t('lc.gates.heading')}</span>
        <div className={styles.gatesButtons}>
          <PixelButton size="sm" disabled={busy} onClick={() => run(false)}>
            {busy ? t('lc.gates.running') : t('lc.gates.run')}
          </PixelButton>
          <PixelButton size="sm" disabled={busy} onClick={() => run(true)}>
            {busy ? t('lc.gates.running') : t('lc.gates.runShadow')}
          </PixelButton>
        </div>
      </div>

      <div className={styles.gateChips}>
        {GATE_KEYS.map((g) => {
          const report = latest[g];
          const state = !report ? 'pending' : report.passed ? 'pass' : 'fail';
          return (
            <span
              key={g}
              className={`${styles.gateChip} ${styles[`gate-${state}`]}`}
              title={report ? `${t('lc.gates.reason')}: ${summarizeGate(report)}` : t('lc.gates.pending')}
            >
              {t(`lc.gates.${g}`)} ·{' '}
              {state === 'pending' ? t('lc.gates.pending') : state === 'pass' ? '✓' : '✗'}
            </span>
          );
        })}
      </div>

      {shadowDetail?.metrics_off && shadowDetail?.metrics_on && (
        <div className={styles.shadowMetrics}>
          <span className={styles.muted}>{t('lc.gates.hits', { n: shadowDetail.target_pattern_hits ?? '?' })}</span>
          <Metric label="precision" off={shadowDetail.metrics_off.precision} on={shadowDetail.metrics_on.precision} />
          <Metric label="recall" off={shadowDetail.metrics_off.recall} on={shadowDetail.metrics_on.recall} />
          <Metric
            label="falseP0"
            off={shadowDetail.metrics_off.false_p0_count}
            on={shadowDetail.metrics_on.false_p0_count}
          />
        </div>
      )}
      {shadowDetail?.gate_reason && (
        <p className={styles.gateReason}>{shadowDetail.gate_reason}</p>
      )}
      {error && <p className={styles.gateError}>{error}</p>}
    </div>
  );
}

function Metric({ label, off, on }: { label: string; off?: number; on?: number }) {
  const fmt = (v?: number) => (v === undefined || v === null ? '—' : v.toFixed(2));
  const delta =
    off !== undefined && on !== undefined && ['precision', 'recall'].includes(label)
      ? on - off
      : null;
  return (
    <span className={styles.metric}>
      <span className={styles.muted}>{label}</span>{' '}
      <span className="px-mono">
        {fmt(off)}→{fmt(on)}
        {delta !== null && (
          <span className={delta >= 0 ? styles.deltaUp : styles.deltaDown}>
            {' '}
            {delta >= 0 ? '+' : ''}
            {delta.toFixed(2)}
          </span>
        )}
      </span>
    </span>
  );
}

function summarizeGate(report: GateReportT): string {
  const d = report.detail ?? {};
  if (Array.isArray(d.violations) && d.violations.length) return String(d.violations[0]);
  if (Array.isArray(d.reasons) && d.reasons.length) return String(d.reasons[0]);
  if (typeof d.gate_reason === 'string') return d.gate_reason;
  if (typeof d.distinct_prd_count === 'number')
    return `${d.distinct_prd_count} distinct PRDs`;
  if (Array.isArray(d.top_matches) && d.top_matches.length) {
    const top = d.top_matches[0] as { skill?: string; similarity?: number };
    return `~${top.skill} ${top.similarity}`;
  }
  return report.evaluator_version || 'ok';
}
