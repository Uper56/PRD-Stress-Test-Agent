import { useCallback, useEffect, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { PixelButton } from '../components/PixelButton';
import { ProposalCard } from '../components/ProposalCard';
import { LibraryView, OverviewView } from '../components/LifecycleViews';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type { Proposal } from '../lib/types';
import styles from './SkillsPage.module.css';

type Tab = 'overview' | 'proposals' | 'library';

/** Skill Lifecycle Center — Overview / Proposals / Library.

 * The page keeps the pixel shell as brand chrome; the three governance
 * views inside use the restrained evidence-first styling defined in
 * LifecycleViews.module.css (product-review decision, HANDOFF §5). */
export function SkillsPage() {
  const { t } = useT();
  const [tab, setTab] = useState<Tab>('overview');
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [distilling, setDistilling] = useState(false);
  const [distillMsg, setDistillMsg] = useState<string | null>(null);
  const [distillError, setDistillError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const loadProposals = useCallback(() => {
    api.proposals().then(setProposals).catch(() => setProposals([]));
  }, []);

  useEffect(loadProposals, [loadProposals, reload]);

  const refreshAll = useCallback(() => {
    setReload((r) => r + 1);
    loadProposals();
  }, [loadProposals]);

  const runDistill = async () => {
    setDistilling(true);
    setDistillMsg(null);
    setDistillError(null);
    try {
      const res = await api.distill();
      setDistillMsg(
        res.found === 0 ? t('distill.none') : t('distill.found', { n: res.found }),
      );
      refreshAll();
    } catch (err) {
      setDistillError(err instanceof Error ? err.message : t('distill.fail'));
    } finally {
      setDistilling(false);
    }
  };

  const tabs: Array<{ key: Tab; label: string; badge?: number }> = [
    { key: 'overview', label: t('lc.tab.overview') },
    { key: 'proposals', label: t('lc.tab.proposals'), badge: proposals.length },
    { key: 'library', label: t('lc.tab.library') },
  ];

  return (
    <div className={styles.layout}>
      <div className={styles.head}>
        <h1>{t('lc.title')}</h1>
        <nav className={styles.tabs} role="tablist">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              role="tab"
              aria-selected={tab === tb.key}
              className={`${styles.tab} ${tab === tb.key ? styles.tabActive : ''}`}
              onClick={() => setTab(tb.key)}
            >
              {tb.label}
              {tb.badge !== undefined && tb.badge > 0 && (
                <span className={styles.tabBadge}>{tb.badge}</span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {tab === 'overview' && <OverviewView onChanged={refreshAll} />}

      {tab === 'proposals' && (
        <section className={styles.distill}>
          <div className={styles.distillBar}>
            <PixelButton variant="primary" disabled={distilling} onClick={() => void runDistill()}>
              {distilling ? t('distill.mining') : t('distill.run')}
            </PixelButton>
            {distillMsg && <span className={styles.distillMsg}>{distillMsg}</span>}
            {distillError && <span className={styles.distillErr}>{distillError}</span>}
          </div>

          {proposals.length === 0 ? (
            <EmptyState
              glyph="▞▚"
              title={t('distill.empty')}
              hint={t('distill.emptyHint')}
            />
          ) : (
            <div className={styles.proposals}>
              {proposals.map((p) => (
                <ProposalCard
                  key={p.proposal_id}
                  proposal={p}
                  onChanged={() => refreshAll()}
                />
              ))}
            </div>
          )}
        </section>
      )}

      {tab === 'library' && <LibraryView onChanged={refreshAll} />}
    </div>
  );
}
