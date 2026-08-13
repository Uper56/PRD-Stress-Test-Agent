import { useCallback, useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type { HistoryItem } from '../lib/types';
import styles from './HistoryRail.module.css';

interface Props {
  selectedId?: string | null;
  onSelect: (runId: string) => void;
  onDeleted?: (runId: string) => void;
}

/** Left-rail run history — Codex-style list with P-count badges and delete. */
export function HistoryRail({ selectedId, onSelect, onDeleted }: Props) {
  const { t } = useT();
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState(false);
  const [confirmId, setConfirmId] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .history()
      .then(setItems)
      .catch(() => setError(true));
  }, []);

  useEffect(load, [load]);

  const doDelete = useCallback(
    async (runId: string) => {
      try {
        await api.historyDelete(runId);
        setItems((prev) => (prev ?? []).filter((r) => r.run_id !== runId));
        setConfirmId(null);
        onDeleted?.(runId);
      } catch {
        setConfirmId(null);
      }
    },
    [onDeleted],
  );

  if (error) return <aside className={styles.rail}>{t('history.loadFail')}</aside>;
  if (items === null) return <aside className={styles.rail}>{t('history.loading')}</aside>;
  if (items.length === 0)
    return (
      <aside className={styles.rail}>
        <div className={styles.empty}>{t('history.empty')}</div>
        <div className={styles.emptyHint}>{t('history.emptyHint')}</div>
      </aside>
    );

  return (
    <aside className={styles.rail}>
      <div className={`px-label ${styles.head}`}>{t('history.heading', { n: items.length })}</div>
      <ul className={styles.list}>
        {items.map((item) => {
          const active = item.run_id === selectedId;
          const confirming = item.run_id === confirmId;
          return (
            <li key={item.run_id} className={styles.itemWrap}>
              <button
                className={`${styles.item} ${active ? styles.itemActive : ''}`}
                onClick={() => onSelect(item.run_id)}
              >
                <div className={styles.itemTop}>
                  <span className={styles.ts}>
                    {item.timestamp.slice(0, 16).replace('T', ' ')}
                  </span>
                  <span className={styles.counts}>
                    {item.p0 > 0 && <em className={styles.p0}>P0×{item.p0}</em>}
                    {item.p1 > 0 && <em className={styles.p1}>P1×{item.p1}</em>}
                    {item.p2 > 0 && <em className={styles.p2}>P2×{item.p2}</em>}
                    {item.p0 + item.p1 + item.p2 === 0 && (
                      <em className={styles.none}>{t('history.noP')}</em>
                    )}
                  </span>
                </div>
                <div className={styles.name}>{item.prd_filename ?? t('history.custom')}</div>
              </button>
              {confirming ? (
                <span className={styles.confirmBar}>
                  <button className={styles.confirmYes} onClick={() => void doDelete(item.run_id)}>
                    {t('history.confirm')}
                  </button>
                  <button className={styles.confirmNo} onClick={() => setConfirmId(null)}>
                    {t('history.cancel')}
                  </button>
                </span>
              ) : (
                <button
                  className={styles.trash}
                  title={t('history.delete')}
                  onClick={() => setConfirmId(item.run_id)}
                >
                  🗑
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
