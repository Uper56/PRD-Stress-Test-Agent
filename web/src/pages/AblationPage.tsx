import { useCallback, useEffect, useRef, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { MetricCard } from '../components/MetricCard';
import { PixelButton } from '../components/PixelButton';
import { api } from '../lib/api';
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

const HEADLINE: { label: string; key: string; fmt: (v: number) => string }[] = [
  { label: '缺陷召回率', key: 'overall_recall', fmt: (v) => v.toFixed(2) },
  { label: 'Precision', key: 'precision', fmt: (v) => v.toFixed(2) },
  { label: '平均耗时 (秒)', key: 'latency_seconds', fmt: (v) => v.toFixed(2) },
  { label: '平均成本 ($)', key: 'cost_usd_estimate', fmt: (v) => v.toFixed(3) },
];

const ROWS: { label: string; key: string; fmt: (v: number) => string }[] = [
  { label: '缺陷召回率', key: 'overall_recall', fmt: (v) => v.toFixed(2) },
  { label: 'Precision', key: 'precision', fmt: (v) => v.toFixed(2) },
  { label: '结构合规率', key: 'structure_compliance', fmt: (v) => v.toFixed(2) },
  { label: '依赖识别召回率', key: 'dependency_recall', fmt: (v) => v.toFixed(2) },
  { label: '矛盾检测召回率', key: 'contradiction_detection', fmt: (v) => v.toFixed(2) },
  { label: 'Severity F1', key: 'severity_classification_f1', fmt: (v) => v.toFixed(2) },
  { label: '可执行性', key: 'actionability', fmt: (v) => v.toFixed(2) },
  { label: '平均耗时 (秒)', key: 'latency_seconds', fmt: (v) => v.toFixed(2) },
  { label: '平均成本 ($)', key: 'cost_usd_estimate', fmt: (v) => v.toFixed(3) },
  { label: '单次产出数', key: 'critique_count', fmt: (v) => v.toFixed(1) },
];

const TREATMENT_LABEL: Record<string, string> = {
  skill_off: 'OFF',
  skill_seed_only: '种子 Skill',
  skill_seed_plus_learned: '种子 + 自学习',
};

/** Ablation lab — Skill 库对系统的贡献，量化成表。 */
export function AblationPage() {
  const [report, setReport] = useState<AblationReport | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [quick, setQuick] = useState(true);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobStatus, setJobStatus] = useState<string | null>(null);
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
        setLoadError(err instanceof Error ? err.message : '加载失败');
        setLoaded(true);
      });
  }, []);

  useEffect(load, [load]);

  useEffect(() => {
    if (!jobId) return;
    pollRef.current = setInterval(async () => {
      try {
        const status = await api.ablationStatus(jobId);
        setJobStatus(status.status);
        if (status.status === 'done') {
          if (pollRef.current) clearInterval(pollRef.current);
          setJobId(null);
          load();
        } else if (status.status === 'failed') {
          if (pollRef.current) clearInterval(pollRef.current);
          setJobId(null);
          setRunError(status.message ?? '消融失败');
        }
      } catch {
        /* keep polling */
      }
    }, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId, load]);

  const rerun = async () => {
    setRunError(null);
    try {
      const { job_id } = await api.ablationRun(quick);
      setJobId(job_id);
      setJobStatus('running');
    } catch (err) {
      setRunError(err instanceof Error ? err.message : '启动失败');
    }
  };

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <h1>消融实验</h1>
        <p className={styles.intro}>
          通过在多种检索条件下重跑每份 PRD 并对照预埋缺陷集打分，量化 Skill 库对系统的贡献。
        </p>
      </div>

      {loadError && <div className={styles.error}>{loadError}</div>}

      {loaded && !report && (
        <EmptyState
          glyph="▚▚"
          title="尚无消融报告"
          hint="点击下方「重新运行消融实验」，或命令行运行 python -m src.eval --quick。快速模式约需 1 分钟。"
        />
      )}

      {report && <ReportBody report={report} />}

      <section className={styles.rerun}>
        <h2>重新运行消融实验</h2>
        <div className={styles.rerunBar}>
          <label className={styles.quickLabel}>
            <input
              type="checkbox"
              checked={quick}
              onChange={(e) => setQuick(e.target.checked)}
            />
            快速模式（每格运行 1 次）
          </label>
          <PixelButton
            variant="primary"
            disabled={jobId !== null}
            onClick={() => void rerun()}
          >
            {jobId ? `运行中…（${jobStatus === 'running' ? '约 1 分钟' : jobStatus}）` : '▶️ 重新运行'}
          </PixelButton>
          {runError && <span className={styles.error}>{runError}</span>}
        </div>
        <p className={styles.disclaimer}>
          数据源：OpenAI gpt-4o-mini（Critics + Supervisor 同模型，supervisor 升级到 gpt-4o
          为后续工作）· 完整方法论见 README。
        </p>
      </section>
    </div>
  );
}

function ReportBody({ report }: { report: AblationReport }) {
  const { treatments, aggregated } = report;
  const on = treatments.includes('skill_seed_plus_learned')
    ? 'skill_seed_plus_learned'
    : treatments[treatments.length - 1];
  const off = treatments.includes('skill_off') ? 'skill_off' : treatments[0];

  return (
    <div className={styles.body}>
      {on && off && on !== off && (
        <section>
          <h2>核心对比：ON vs OFF</h2>
          <div className={styles.metrics}>
            {HEADLINE.map(({ label, key, fmt }) => {
              const onV = aggregated[on]?.[`${key}_mean`] ?? 0;
              const offV = aggregated[off]?.[`${key}_mean`] ?? 0;
              const delta = onV - offV;
              return (
                <MetricCard
                  key={key}
                  label={label}
                  value={fmt(onV)}
                  delta={`${delta >= 0 ? '+' : ''}${delta.toFixed(2)} vs OFF`}
                  tone={delta >= 0 ? 'up' : 'down'}
                />
              );
            })}
          </div>
        </section>
      )}

      <section>
        <h2>对比表</h2>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th>指标</th>
                {treatments.map((t) => (
                  <th key={t}>{TREATMENT_LABEL[t] ?? t}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ROWS.map(({ label, key, fmt }) => (
                <tr key={key}>
                  <td>{label}</td>
                  {treatments.map((t) => (
                    <td key={t} className="px-mono">
                      {fmt(aggregated[t]?.[`${key}_mean`] ?? 0)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2>各实验组对比图</h2>
        <div className={styles.charts}>
          {HEADLINE.map(({ label, key }) => {
            const values = treatments.map((t) => aggregated[t]?.[`${key}_mean`] ?? 0);
            const max = Math.max(...values, 1e-9);
            return (
              <div key={key} className={styles.chart}>
                <div className={`px-label ${styles.chartLabel}`}>{label}</div>
                {treatments.map((t, i) => (
                  <div key={t} className={styles.chartRow}>
                    <span className={styles.chartName}>{TREATMENT_LABEL[t] ?? t}</span>
                    <div className={styles.chartTrack}>
                      <div
                        className={`${styles.chartBar} ${t === on ? styles.chartBarOn : ''}`}
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
        生成于 {report.timestamp ?? '?'} · PRD: {report.prds_used?.length ?? 0} 份 · 每组运行:{' '}
        {report.runs_per_treatment ?? 1}
      </p>
    </div>
  );
}
