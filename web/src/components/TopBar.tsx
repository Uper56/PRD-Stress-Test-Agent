import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { api } from '../lib/api';
import type { Meta } from '../lib/types';
import styles from './TopBar.module.css';

const NAV = [
  { to: '/', label: '评审', end: true },
  { to: '/skills', label: 'Skill 库' },
  { to: '/ablation', label: '消融实验' },
];

/** App chrome: pixel logo, primary nav, live model/quota status chip. */
export function TopBar() {
  const [meta, setMeta] = useState<Meta | null>(null);

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  const quotaLabel = !meta
    ? '连接中…'
    : meta.rate.disabled
      ? `本地模式 · ${meta.model}`
      : `今日剩余 ${meta.rate.remaining_global}/${meta.rate.per_day} 次`;

  return (
    <header className={styles.bar}>
      <div className={styles.logo}>
        <span className={styles.logoMark} aria-hidden>
          ◤◢
        </span>
        PIXEL·PRD
      </div>
      <nav className={styles.nav}>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `${styles.tab} ${isActive ? styles.tabActive : ''}`
            }
          >
            {item.label}
          </NavLink>
        ))}
      </nav>
      <div className={styles.status} title="模型与 demo 配额">
        <span className={styles.statusDot} aria-hidden />
        {quotaLabel}
      </div>
    </header>
  );
}
