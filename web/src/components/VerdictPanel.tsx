import { useT } from '../lib/i18n';
import type { Verdict } from '../lib/types';
import { SeverityBadge } from './SeverityBadge';
import styles from './VerdictPanel.module.css';

interface Props {
  verdict: Verdict;
}

/** Supervisor verdict — executive summary + three severity columns. */
export function VerdictPanel({ verdict }: Props) {
  const { t } = useT();
  const groups: { key: keyof Verdict; severity: string; label: string }[] = [
    { key: 'p0_blockers', severity: 'P0', label: t('verdict.p0') },
    { key: 'p1_concerns', severity: 'P1', label: t('verdict.p1') },
    { key: 'p2_suggestions', severity: 'P2', label: t('verdict.p2') },
  ];

  return (
    <div className={`px-card px-card--accent ${styles.wrap}`}>
      <div className={styles.headline}>
        <span className={`px-label ${styles.kicker}`}>{t('verdict.kicker')}</span>
        {verdict.executive_summary && (
          <p className={styles.summary}>{verdict.executive_summary}</p>
        )}
      </div>

      <div className={styles.columns}>
        {groups.map(({ key, severity, label }) => {
          const items = (verdict[key] as string[] | undefined) ?? [];
          return (
            <div key={key} className={`${styles.column} ${styles[`col${severity.toLowerCase()}`]}`}>
              <div className={styles.colHead}>
                <SeverityBadge severity={severity} size="sm" />
                <span className={styles.colLabel}>{label}</span>
                <span className={styles.colCount}>({items.length})</span>
              </div>
              {items.length === 0 ? (
                <div className={styles.none}>{t('verdict.none')}</div>
              ) : (
                <ul className={styles.items}>
                  {items.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              )}
            </div>
          );
        })}
      </div>

      {(verdict.conflict_resolutions?.length ?? 0) > 0 && (
        <div className={styles.conflicts}>
          <div className={`px-label ${styles.conflictsHead}`}>{t('verdict.conflicts')}</div>
          <ul className={styles.items}>
            {verdict.conflict_resolutions!.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
