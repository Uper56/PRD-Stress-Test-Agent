import { useT } from '../lib/i18n';
import styles from './ThinkingTerminal.module.css';

interface Props {
  text: string;
  inProgress: boolean;
  label?: string;
}

/** Streamed supervisor reasoning — terminal panel with a blinking block cursor. */
export function ThinkingTerminal({ text, inProgress, label }: Props) {
  const { t } = useT();
  const resolvedLabel = label ?? t('deck.reasoningLabel');
  if (!text && !inProgress) return null;
  return (
    <div className={styles.terminal}>
      <div className={styles.head}>
        <span className={styles.prompt}>▸</span>
        <span className="px-label">
          {resolvedLabel}
          {inProgress ? t('deck.reasoningProgress') : t('deck.reasoningDone')}
        </span>
      </div>
      <pre className={styles.body}>
        {text}
        {inProgress && <span className="px-cursor" aria-hidden />}
      </pre>
    </div>
  );
}
