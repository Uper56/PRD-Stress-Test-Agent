import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type { Meta } from '../lib/types';
import styles from './TopBar.module.css';

/** App chrome: pixel logo, primary nav, language toggle, live model/quota chip. */
export function TopBar() {
  const [meta, setMeta] = useState<Meta | null>(null);
  const { lang, setLang, t } = useT();

  useEffect(() => {
    api.meta().then(setMeta).catch(() => setMeta(null));
  }, []);

  const nav = [
    { to: '/', label: t('nav.review'), end: true },
    { to: '/skills', label: t('nav.skills'), end: false },
    { to: '/ablation', label: t('nav.ablation'), end: false },
  ];

  const quotaLabel = !meta
    ? t('status.connecting')
    : meta.rate.disabled
      ? t('status.local', { model: meta.model })
      : t('status.quota', { a: meta.rate.remaining_global, b: meta.rate.per_day });

  return (
    <header className={styles.bar}>
      <div className={styles.logo}>
        <span className={styles.logoMark} aria-hidden>
          ◤◢
        </span>
        PIXEL·PRD
      </div>
      <nav className={styles.nav}>
        {nav.map((item) => (
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
      <button
        className={styles.langToggle}
        onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
        title="切换语言 / Switch language"
      >
        {t('lang.toggle')}
      </button>
      <div className={styles.status} title="模型与 demo 配额">
        <span className={styles.statusDot} aria-hidden />
        {quotaLabel}
      </div>
    </header>
  );
}
