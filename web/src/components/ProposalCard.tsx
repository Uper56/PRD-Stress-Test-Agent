import { useState } from 'react';
import { api } from '../lib/api';
import type { Proposal } from '../lib/types';
import { PixelButton } from './PixelButton';
import styles from './ProposalCard.module.css';

interface Props {
  proposal: Proposal;
  onChanged: () => void;
}

const scoreTone = (score: number) => (score >= 0.8 ? '🟢' : score >= 0.7 ? '🟡' : '🔴');

/** One distilled-skill proposal — approve / reject / edit + evidence. */
export function ProposalCard({ proposal, onChanged }: Props) {
  const [showEvidence, setShowEvidence] = useState(false);
  const [showMd, setShowMd] = useState(false);
  const [edited, setEdited] = useState(proposal.proposed_skill_md);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const editedNow = edited !== proposal.proposed_skill_md;

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : '操作失败');
      setBusy(false);
    }
  };

  return (
    <div className={`px-card ${styles.card}`}>
      <div className={styles.head}>
        <span className={styles.score}>{scoreTone(proposal.generalization_score)}</span>
        <span className={styles.name}>{proposal.proposed_name}</span>
        <span className={styles.gen}>gen={proposal.generalization_score.toFixed(2)}</span>
      </div>

      <div className={styles.caption}>
        在 {proposal.pattern_frequency} 份不同 PRD 中重复出现 · 注入到{' '}
        {(proposal.injected_into ?? []).join(', ') || '—'}
      </div>

      <div className={styles.progressBar} aria-hidden>
        <div
          className={styles.progressFill}
          style={{ width: `${Math.min(Math.max(proposal.generalization_score, 0), 1) * 100}%` }}
        />
      </div>

      <div className={styles.actions}>
        <PixelButton size="sm" onClick={() => setShowEvidence((v) => !v)}>
          📎 证据 ({proposal.evidence.length})
        </PixelButton>
        <PixelButton size="sm" onClick={() => setShowMd((v) => !v)}>
          📄 SKILL.md
        </PixelButton>
      </div>

      {showEvidence && (
        <ul className={styles.evidence}>
          {proposal.evidence.map((ev, i) => (
            <li key={i}>
              <span className="px-mono">
                {String(ev.run_id ?? '?').slice(0, 12)}
              </span>{' '}
              — {String(ev.critique_excerpt ?? '')}
            </li>
          ))}
        </ul>
      )}

      {showMd && (
        <textarea
          className={styles.editor}
          value={edited}
          onChange={(e) => setEdited(e.target.value)}
          rows={10}
        />
      )}

      <div className={styles.buttons}>
        <PixelButton
          size="sm"
          variant="success"
          disabled={busy}
          onClick={() =>
            run(() =>
              api.proposalApprove(proposal.proposal_id, editedNow ? edited : undefined),
            )
          }
        >
          ✅ 采纳
        </PixelButton>
        <PixelButton
          size="sm"
          variant="danger"
          disabled={busy}
          onClick={() => run(() => api.proposalReject(proposal.proposal_id))}
        >
          ❌ 驳回
        </PixelButton>
        <PixelButton
          size="sm"
          disabled={busy || !editedNow}
          onClick={() => run(() => api.proposalSaveEdit(proposal.proposal_id, edited))}
        >
          ✏️ 保存修改
        </PixelButton>
      </div>

      {error && <div className={styles.error}>{error}</div>}
    </div>
  );
}
