import { useCallback, useEffect, useRef, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { MetricCard } from '../components/MetricCard';
import { PixelButton } from '../components/PixelButton';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import styles from './AblationPage.module.css';

interface Aggregated {
  [treatment: string]: Record<string, number>;
}

interface AblationReport {
  treatments: string[];
  aggregated: Aggregated;
  timestamp?: string;
  prds_used?: string[];
  runs_per_treatment?: number;
}

/** Ablation lab — Skill 库对系统的贡献，量化成表。 */
export function AblationPage() {
  const { t } = useT();
  const [report, setReport] = useState<AblationReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [quick, setQuick] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [runError, setRunError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(() => {
    api
      .ablation()
      .then((r) => {
        setReport((r as AblationReport | null) ?? null);
        setLoaded(true);
      })
      .catch((err) => {
        setLoadError(err instanceof Error ? err.message : t('ablation.loadFail'));
        setLoaded(true);
      });
  }, [t]);

  useEffect(load, [load]);

  useEffect(() => {
    if (!jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.ablationStatus(jobId);
        if (status.status === 'done') {
          if (pollRef.current) clearInterval(pollRef.current);
          setJobId(null);
          load();
        } else if (status.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current);
          setJobId(null);
          setRunError(status.message ?? t('ablation.fail'));
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId, load, t]);

  const rerun = async () => {
    setRunError(null);
    try {
      const { job_id } = await api.ablationRun(quick);
      setJobId(job_id);
    } catch (err) {
      setRunError(err instanceof Error ? err.message : t('ablation.startFail'));
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <h1>{t('ablation.heading')}</h1>
        <p className={styles.intro}>{t('ablation.intro')}</p>
      </div>

      {loadError && <div className={styles.error}>{loadError}</div>}

      {loaded && !report && (
        <EmptyState
          glyph="▚▚"
          title={t('ablation.empty')}
          hint={t('ablation.emptyHint')}
        />
      )}

      {report && <ReportBody report={report} />}

      <section className={styles.rerun}>
        <h2>{t('ablation.rerun')}</h2>
        <div className={styles.rerunBar}>
          <label className={styles.quickLabel}>
            <input
              type="checkbox"
              checked={quick}
              onChange={(e) => setQuick(e.target.checked)}
            />
            {t('ablation.quick')}
          </label>
          <PixelButton
            variant="primary"
            disabled={jobId !== null}
            onClick={() => void rerun()}
          >
            {jobId ? t('ablation.running') : t('ablation.runBtn')}
          </PixelButton>
          {runError && <span className={styles.error}>{runError}</span>}
        </div>
        <p className={styles.disclaimer}>{t('ablation.disclaimer')}</p>
      </section>
    </div>
  );
}

function ReportBody({ report }: { report: AblationReport }) {
  const { t } = useT();
  const { treatments, aggregated } = report;
  const on = treatments.includes('skill_seed_plus_learned')
    ? 'skill_seed_plus_learned'
    : treatments[treatments.length - 1];
  const off = treatments.includes('skill_off') ? 'skill_off' : treatments[0];

  const headline = [
    { label: t('ablation.recall'), key: 'overall_recall', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.precision'), key: 'precision', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.latency'), key: 'latency_seconds', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.cost'), key: 'cost_usd_estimate', fmt: (v: number) => v.toFixed(3) },
  ];

  const rows = [
    { label: t('ablation.rowRecall'), key: 'overall_recall', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowPrecision'), key: 'precision', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowStructure'), key: 'structure_compliance', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowDependency'), key: 'dependency_recall', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowContradiction'), key: 'contradiction_detection', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowSeverity'), key: 'severity_classification_f1', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowActionability'), key: 'actionability', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowLatency'), key: 'latency_seconds', fmt: (v: number) => v.toFixed(2) },
    { label: t('ablation.rowCost'), key: 'cost_usd_estimate', fmt: (v: number) => v.toFixed(3) },
    { label: t('ablation.rowCritiques'), key: 'critique_count', fmt: (v: number) => v.toFixed(1) },
  ];

  const treatmentLabel = (treat: string) =>
    treat === 'skill_off'
      ? 'OFF'
      : treat === 'skill_seed_only'
        ? t('ablation.seed')
        : treat === 'skill_seed_plus_learned'
          ? t('ablation.learned')
          : treat;

  return (
    <div className={styles.body}>
      {on && off && on !== off && (
        <section>
          <h2>{t('ablation.headline')}</h2>
          <div className={styles.metrics}>
            {headline.map(({ label, key, fmt }) => {
              const onV = aggregated[on]?.[`${key}_mean`] ?? 0;
              const offV = aggregated[off]?.[`${key}_mean`] ?? 0;
              const delta = onV - offV;
              return (
                <MetricCard
                  key={key}
                  label={label}
                  value={fmt(onV)}
                  delta={t('ablation.delta', {
                    d: `${delta >= 0 ? '+' : ''}${delta.toFixed(2)}`,
                  })}
                  tone={delta >= 0 ? 'up' : 'down'}
                />
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h2>{t('ablation.table')}</h2>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>{t('ablation.metric')}</th>
                {treatments.map((treat) => (
                  <th key={treat}>{treatmentLabel(treat)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map(({ label, key, fmt }) => (
                <tr key={key}>
                  <td>{label}</td>
                  {treatments.map((treat) => (
                    <td key={treat} className="px-mono">
                      {fmt(aggregated[treat]?.[`${key}_mean`] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>{t('ablation.charts')}</h2>
        <div className={styles.charts}>
          {headline.map(({ label, key }) => {
            const values = treatments.map((treat) => aggregated[treat]?.[`${key}_mean`] ?? 0);
            const max = Math.max(...values, 1e-9);
            return (
              <div key={key} className={styles.chart}>
                <div className={`px-label ${styles.chartLabel}`}>{label}</div>
                {treatments.map((treat, i) => (
                  <div key={treat} className={styles.chartRow}>
                    <span className={styles.chartName}>{treatmentLabel(treat)}</span>
                    <div className={styles.chartTrack}>
                      <div
                        className={`${styles.chartBar} ${treat === on ? styles.chartBarOn : ''}`}
                        style={{ width: `${(values[i] / max) * 100}%` }}
                      />
                    </div>
                    <span className={`px-mono ${styles.chartVal}`}>{values[i].toFixed(2)}</span>
                  </div>
                ))}
              </div>
            );
          })}
        </div>
      </section>

      <p className={styles.meta}>
        {t('ablation.meta', {
          ts: report.timestamp ?? '?',
          n: report.prds_used?.length ?? 0,
          r: report.runs_per_treatment ?? 1,
        })}
      </p>
    </div>
  );
}
