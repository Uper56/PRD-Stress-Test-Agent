import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type { Skill } from '../lib/types';
import { PixelButton } from './PixelButton';
import styles from './SkillCard.module.css';

interface Props {
  skill: Skill;
  active: boolean;
  onSelect: () => void;
  onDeprecate?: () => void;
}

/** One row in the Skill library list — name, description, usage count. */
export function SkillCard({ skill, active, onSelect, onDeprecate }: Props) {
  const { t } = useT();
  return (
    <button
      className={`${styles.card} ${active ? styles.active : ''}`}
      onClick={onSelect}
    >
      <div className={styles.top}>
        <span className={styles.name}>{skill.name}</span>
        <span className={styles.usage}>×{skill.usage_count ?? 0}</span>
      </div>
      <div className={styles.desc}>{(skill.description ?? '').slice(0, 72) || '—'}</div>
      {active && onDeprecate && (
        <span
          className={styles.deprecate}
          role="button"
          tabIndex={0}
          onClick={(e) => {
            e.stopPropagation();
            onDeprecate();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.stopPropagation();
              onDeprecate();
            }
          }}
        >
          {t('skills.deprecate')}
        </span>
      )}
    </button>
  );
}

/** Detail pane: description, tech metadata, SKILL.md viewer. */
export function SkillDetail({ skill }: { skill: Skill }) {
  const { t } = useT();
  const [md, setMd] = useState<string | null>(null);
  const [showMd, setShowMd] = useState(false);
  const [showTech, setShowTech] = useState(false);
  const [mdError, setMdError] = useState<string | null>(null);

  useEffect(() => {
    setMd(null);
    setShowMd(false);
    setMdError(null);
  }, [skill.name]);

  const loadMd = async () => {
    if (md !== null) return;
    try {
      setMd((await api.skillMd(skill.name)).md);
    } catch (err) {
      setMdError(err instanceof Error ? err.message : t('skills.loadFail'));
    }
  };

  return (
    <div className={`px-card ${styles.detail}`}>
      <div className={styles.detailName}>{skill.name}</div>
      <div className={styles.detailDesc}>{skill.description ?? '—'}</div>
      <div className={styles.detailUsage}>
        {t('skills.usage', { n: skill.usage_count ?? 0 })}
      </div>

      <div className={styles.detailActions}>
        <PixelButton size="sm" onClick={() => setShowTech((v) => !v)}>
          {t('skills.tech')}
        </PixelButton>
        <PixelButton
          size="sm"
          onClick={() => {
            setShowMd((v) => !v);
            if (!showMd) void loadMd();
          }}
        >
          {t('skills.md')}
        </PixelButton>
      </div>

      {showTech && (
        <div className={styles.tech}>
          <span className="px-mono">
            {t('skills.techMeta', {
              v: skill.version ?? '1.0',
              w: skill.created_by ?? '?',
              r: (skill.injected_into ?? []).join(', ') || '—',
            })}
          </span>
        </div>
      )}

      {showMd && (
        <div className={styles.md}>
          {mdError ? (
            <div className={styles.mdError}>{mdError}</div>
          ) : md === null ? (
            <div className={styles.mdLoading}>{t('history.loading')}</div>
          ) : (
            <pre>{md}</pre>
          )}
        </div>
      )}
    </div>
  );
}
