import { useCallback, useRef, useState } from 'react';
import { postSSE } from '../lib/api';
import type { Critique } from '../lib/types';
import { PixelButton } from './PixelButton';
import { SeverityBadge } from './SeverityBadge';
import styles from './CritiqueCard.module.css';

export type FeedbackState = 'accepted' | 'rejected' | null;

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

interface Props {
  critique: Critique;
  /** Live-run discuss endpoint (only present while the run is in the hub) */
  discussUrl?: string | null;
  feedback?: FeedbackState;
  onFeedback?: (accepted: boolean) => void;
}

const MAX_DIALOG_ROUNDS = 5; // mirrors MAX_DIALOG_ROUNDS in src/agents/critique_dialog.py

/** One critic finding — evidence / suggested fix, feedback, follow-up chat. */
export function CritiqueCard({ critique, discussUrl, feedback, onFeedback }: Props) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [draft, setDraft] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [dialogError, setDialogError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const rounds = messages.filter((m) => m.role === 'user').length;
  const capReached = rounds >= MAX_DIALOG_ROUNDS;
  const uid = critique.uid ?? '';
  const skillId = critique.skill_id;

  const send = useCallback(async () => {
    const content = draft.trim();
    if (!content || streaming || !discussUrl || !uid) return;
    const history: ChatMsg[] = [...messages, { role: 'user', content }];
    setMessages(history);
    setDraft('');
    setStreaming(true);
    setDialogError(null);
    let acc = '';
    try {
      await postSSE(
        discussUrl,
        { critique_uid: uid, messages: history.map((m) => ({ role: m.role, content: m.content })) },
        (ev) => {
          if (ev.event === 'delta') {
            acc += String(ev.data.delta ?? '');
            setMessages([...history, { role: 'assistant', content: acc }]);
          } else if (ev.event === 'error') {
            setDialogError(String(ev.data.message ?? '追问失败'));
          }
        },
      );
      if (acc) setMessages([...history, { role: 'assistant', content: acc }]);
    } catch (err) {
      setDialogError(err instanceof Error ? err.message : '追问失败');
    } finally {
      setStreaming(false);
    }
  }, [draft, streaming, discussUrl, uid, messages]);

  return (
    <div className={`px-card ${styles.card}`}>
      <div className={styles.header}>
        <SeverityBadge severity={critique.severity} size="sm" />
        <div className={styles.titleBlock}>
          <div className={styles.finding}>{critique.finding}</div>
          <div className={styles.meta}>
            <span className="px-mono">claim {critique.claim_id ?? '?'}</span>
            {skillId && <span className="px-chip">Skill · {skillId}</span>}
          </div>
        </div>
      </div>

      {(critique.evidence || critique.suggested_fix) && (
        <div className={styles.fields}>
          {critique.evidence && (
            <div>
              <div className={`px-label ${styles.fieldLabel}`}>原文依据</div>
              <div className={styles.fieldValue}>{critique.evidence}</div>
            </div>
          )}
          {critique.suggested_fix && (
            <div>
              <div className={`px-label ${styles.fieldLabel}`}>建议改进</div>
              <div className={styles.fieldValue}>{critique.suggested_fix}</div>
            </div>
          )}
        </div>
      )}

      <div className={styles.actions}>
        {onFeedback && skillId && (
          <>
            <PixelButton
              size="sm"
              variant="success"
              disabled={feedback !== null}
              onClick={() => onFeedback(true)}
              title="计入 Skill acceptance_rate"
            >
              ✓ 采纳
            </PixelButton>
            <PixelButton
              size="sm"
              variant="danger"
              disabled={feedback !== null}
              onClick={() => onFeedback(false)}
              title="计入 Skill acceptance_rate"
            >
              ✗ 误报
            </PixelButton>
            {feedback === 'accepted' && <span className={styles.feedbackNote}>已记录为 ✓ 采纳</span>}
            {feedback === 'rejected' && <span className={styles.feedbackNote}>已标记为误报</span>}
          </>
        )}
        {discussUrl && (
          <PixelButton size="sm" onClick={() => setOpen((v) => !v)}>
            {open ? '💬 收起追问' : '💬 继续追问'}
          </PixelButton>
        )}
      </div>

      {open && discussUrl && (
        <div className={styles.dialog} ref={scrollRef}>
          {messages.map((m, i) => (
            <div key={i} className={`${styles.msg} ${styles[m.role]}`}>
              <span className={styles.msgRole}>{m.role === 'user' ? '你' : critique.critic_id}</span>
              <span className={styles.msgBody}>{m.content}</span>
            </div>
          ))}
          {streaming && (
            <div className={`${styles.msg} ${styles.assistant}`}>
              <span className={styles.msgRole}>{critique.critic_id}</span>
              <span className={styles.msgBody}>
                思考中<span className="px-cursor" aria-hidden />
              </span>
            </div>
          )}
          {dialogError && <div className={styles.dialogError}>{dialogError}</div>}
          {capReached ? (
            <div className={styles.capNote}>
              🛑 已达到追问上限（{MAX_DIALOG_ROUNDS} 轮）。如需继续请关闭后重开。
            </div>
          ) : (
            <div className={styles.dialogInput}>
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.nativeEvent.isComposing) void send();
                }}
                placeholder={`继续追问 ${critique.critic_id}…`}
                disabled={streaming}
              />
              <PixelButton size="sm" variant="primary" onClick={() => void send()} disabled={streaming || !draft.trim()}>
                发送
              </PixelButton>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
