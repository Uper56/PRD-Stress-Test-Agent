import styles from './ThinkingTerminal.module.css';

interface Props {
  text: string;
  inProgress: boolean;
  label?: string;
}

/** Streamed supervisor reasoning — terminal panel with a blinking block cursor. */
export function ThinkingTerminal({
  text,
  inProgress,
  label = '推理过程',
}: Props) {
  if (!text && !inProgress) return null;
  return (
    <div className={styles.terminal}>
      <div className={styles.head}>
        <span className={styles.prompt}>▸</span>
        <span className="px-label">
          {label}
          {inProgress ? '…' : '（完成）'}
        </span>
      </div>
      <pre className={styles.body}>
        {text}
        {inProgress && <span className="px-cursor" aria-hidden />}
      </pre>
    </div>
  );
}
