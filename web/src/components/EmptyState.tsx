import type { ReactNode } from 'react';
import styles from './EmptyState.module.css';

interface Props {
  /** Pixel-art-ish ASCII glyph shown large */
  glyph?: string;
  title: string;
  hint?: string;
  action?: ReactNode;
}

/** Quiet empty state — used everywhere a panel has nothing to show yet. */
export function EmptyState({ glyph = '▚▚', title, hint, action }: Props) {
  return (
    <div className={`px-card ${styles.wrap}`}>
      <div className={styles.glyph} aria-hidden>
        {glyph}
      </div>
      <div className={styles.title}>{title}</div>
      {hint && <div className={styles.hint}>{hint}</div>}
      {action && <div className={styles.action}>{action}</div>}
    </div>
  );
}
