import { useCallback, useEffect, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { PixelButton } from '../components/PixelButton';
import { ProposalCard } from '../components/ProposalCard';
import { SkillCard, SkillDetail } from '../components/SkillCard';
import { api } from '../lib/api';
import { useT } from '../lib/i18n';
import type { Proposal, Skill } from '../lib/types';
import styles from './SkillsPage.module.css';

/** Skill library — browse, curate, and review distilled proposals. */
export function SkillsPage() {
  const { t } = useT();
  const [skills, setSkills] = useState<Skill[] | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [proposals, setProposals] = useState<Proposal[]>([]);
  const [distilling, setDistilling] = useState(false);
  const [distillMsg, setDistillMsg] = useState<string | null>(null);
  const [distillError, setDistillError] = useState<string | null>(null);
  const [reload, setReload] = useState(0);

  const load = useCallback(() => {
    api.skills().then((list) => {
      setSkills(list);
      setSelectedName((cur) => cur ?? list[0]?.name ?? null);
    });
    api.proposals().then(setProposals).catch(() => setProposals([]));
  }, []);

  useEffect(load, [load, reload]);

  const runDistill = async () => {
    setDistilling(true);
    setDistillMsg(null);
    setDistillError(null);
    try {
      const res = await api.distill();
      setDistillMsg(
        res.found === 0 ? t('distill.none') : t('distill.found', { n: res.found }),
      );
      setReload((r) => r + 1);
    } catch (err) {
      setDistillError(err instanceof Error ? err.message : t('distill.fail'));
    } finally {
      setDistilling(false);
    }
  };

  const handleDeprecate = async (name: string) => {
    await api.skillDeprecate(name);
    setReload((r) => r + 1);
    if (selectedName === name) setSelectedName(null);
  };

  const selected = skills?.find((s) => s.name === selectedName) ?? null;

  return (
    <div className={styles.layout}>
      <section className={styles.library}>
        <div className={styles.head}>
          <h1>{t('skills.heading')}</h1>
          <span className={styles.count}>
            {skills ? t('skills.count', { n: skills.length }) : '…'}
          </span>
        </div>

        {skills && skills.length === 0 ? (
          <EmptyState glyph="▚▚" title={t('skills.empty')} hint={t('skills.emptyHint')} />
        ) : (
          <div className={styles.browser}>
            <div className={styles.list}>
              {(skills ?? []).map((s) => (
                <SkillCard
                  key={s.name}
                  skill={s}
                  active={s.name === selectedName}
                  onSelect={() => setSelectedName(s.name)}
                  onDeprecate={() => void handleDeprecate(s.name)}
                />
              ))}
            </div>
            <div className={styles.detail}>
              {selected ? (
                <SkillDetail key={selected.name} skill={selected} />
              ) : (
                <EmptyState glyph="▚▚" title={t('skills.select')} />
              )}
            </div>
          </div>
        )}
      </section>

      <section className={styles.distill}>
        <div className={styles.head}>
          <h1>{t('distill.heading')}</h1>
          <span className={styles.count}>{t('distill.sub')}</span>
        </div>

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
                onChanged={() => setReload((r) => r + 1)}
              />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
