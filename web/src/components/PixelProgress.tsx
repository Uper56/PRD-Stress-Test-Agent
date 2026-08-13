import styles from './PixelProgress.module.css';

interface Props {
  /** Number of total blocks */
  total: number;
  /** Number of filled blocks */
  filled: number;
  /** Labels rendered next to the bar (usually the current stage name) */
  label?: string;
  active?: boolean;
}

/** Blocky stage progress bar — the 8-bit "waiting room" of a run. */
export function PixelProgress({ total, filled, label, active = false }: Props) {
  const clamped = Math.max(0, Math.min(filled, total));
  return (
    <div className={styles.wrap} role="progressbar" aria-valuenow={clamped} aria-valuemax={total}>
      <div className={styles.blocks}>
        {Array.from({ length: total }, (_, i) => (
          <span
            key={i}
            className={`${styles.block} ${i < clamped ? styles.on : ''} ${
              active && i === clamped ? styles.current : ''
            }`}
          />
        ))}
      </div>
      {label && <span className={`px-label ${styles.label}`}>{label}</span>}
    </div>
  );
}
