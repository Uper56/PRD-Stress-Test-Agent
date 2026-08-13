import { useCallback, useEffect, useState } from 'react';
import { EmptyState } from '../components/EmptyState';
import { PixelButton } from '../components/PixelButton';
import { ProposalCard } from '../components/ProposalCard';
import { SkillCard, SkillDetail } from '../components/SkillCard';
import { api } from '../lib/api';
import type { Proposal, Skill } from '../lib/types';
import styles from './SkillsPage.module.css';

/** Skill library — browse, curate, and review distilled proposals. */
export function SkillsPage() {
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
      setDistillMsg(res.found === 0 ? '暂未发现稳定的新 Skill 候选' : `发现 ${res.found} 个候选 Skill`);
      setReload((r) => r + 1);
    } catch (err) {
      setDistillError(err instanceof Error ? err.message : '提炼失败');
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
          <h1>Skill 库</h1>
          <span className={styles.count}>{skills ? `${skills.length} 个 Skill 启用中` : '…'}</span>
        </div>

        {skills && skills.length === 0 ? (
          <EmptyState glyph="▚▚" title="Skill 库为空" hint="评审跑起来后，采纳反馈会塑造 Skill 库" />
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
                <EmptyState glyph="▚▚" title="选择一个 Skill 查看详情" />
              )}
            </div>
          </div>
        )}
      </section>

      <section className={styles.distill}>
        <div className={styles.head}>
          <h1>Skill 提炼</h1>
          <span className={styles.count}>从历史评审中挖掘重复模式</span>
        </div>

        <div className={styles.distillBar}>
          <PixelButton variant="primary" disabled={distilling} onClick={() => void runDistill()}>
            {distilling ? '挖掘中…' : '🔍 提炼 Skill'}
          </PixelButton>
          {distillMsg && <span className={styles.distillMsg}>{distillMsg}</span>}
          {distillError && <span className={styles.distillErr}>{distillError}</span>}
        </div>

        {proposals.length === 0 ? (
          <EmptyState
            glyph="▞▚"
            title="暂无待审议的 Skill 提案"
            hint="点击「提炼 Skill」，系统会跨 PRD 挖掘重复出现的盲点模式，待你确认后加入 Skill 库。"
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
