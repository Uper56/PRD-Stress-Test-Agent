import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import type { HistoryItem } from '../lib/types';
import styles from './HistoryRail.module.css';

interface Props {
  selectedId?: string | null;
  onSelect: (runId: string) => void;
}

/** Left-rail run history — Codex-style conversation list with P-count badges. */
export function HistoryRail({ selectedId, onSelect }: Props) {
  const [items, setItems] = useState<HistoryItem[] | null>(null);
  const [error, setError] = useState(false);

  const load = () => {
    api
      .history()
      .then(setItems)
      .catch(() => setError(true));
  };

  useEffect(load, []);

  if (error) return <aside className={styles.rail}>无法加载历史记录</aside>;
  if (items === null) return <aside className={styles.rail}>加载中…</aside>;
  if (items.length === 0)
    return (
      <aside className={styles.rail}>
        <div className={styles.empty}>还没跑过评审</div>
        <div className={styles.emptyHint}>点上方「开始评审」试一下</div>
      </aside>
    );

  return (
    <aside className={styles.rail}>
      <div className={`px-label ${styles.head}`}>历史评审 · {items.length}</div>
      <ul className={styles.list}>
        {items.map((item) => {
          const active = item.run_id === selectedId;
          return (
            <li key={item.run_id}>
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
                      <em className={styles.none}>无 P 项</em>
                    )}
                  </span>
                </div>
                <div className={styles.name}>
                  {item.prd_filename ?? '自定义 PRD'}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
