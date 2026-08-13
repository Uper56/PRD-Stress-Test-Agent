import styles from './MetricCard.module.css';

interface Props {
  label: string;
  value: string;
  delta?: string | null;
  tone?: 'up' | 'down' | 'neutral';
}

/** Headline stat card — used on the ablation page. */
export function MetricCard({ label, value, delta, tone = 'neutral' }: Props) {
  return (
    <div className="px-card">
      <div className={styles.body}>
        <div className={`px-label ${styles.label}`}>{label}</div>
        <div className={styles.value}>{value}</div>
        {delta !== undefined && delta !== null && (
          <div className={`${styles.delta} ${styles[tone]}`}>{delta}</div>
        )}
      </div>
    </div>
  );
}
