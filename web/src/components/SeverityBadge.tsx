import styles from './SeverityBadge.module.css';

interface Props {
  severity: string;
  size?: 'sm' | 'md';
}

/** P0/P1/P2 severity chip — semantic colours, never brand colours. */
export function SeverityBadge({ severity, size = 'md' }: Props) {
  const sev = (severity || '?').toUpperCase();
  const klass = ['P0', 'P1', 'P2'].includes(sev) ? sev.toLowerCase() : 'unknown';
  return (
    <span className={`${styles.badge} ${styles[klass]} ${styles[size]}`}>{sev}</span>
  );
}
