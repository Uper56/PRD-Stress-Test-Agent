import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { PixelButton } from './PixelButton';
import styles from './Composer.module.css';

export type Source = 'paste' | 'golden' | 'upload';

export interface ComposerPayload {
  prdText: string;
  prdFilename?: string;
}

interface Props {
  onRun: (payload: ComposerPayload) => void;
  /** Demo quota error surfaced from the API (429) */
  quotaError?: string | null;
  running: boolean;
}

const SOURCES: { id: Source; label: string }[] = [
  { id: 'paste', label: '粘贴文本' },
  { id: 'golden', label: '选择内置 PRD' },
  { id: 'upload', label: '上传文件' },
];

/** The PRD intake area — three sources, one「开始评审 ▶」. */
export function Composer({ onRun, quotaError, running }: Props) {
  const [source, setSource] = useState<Source>('paste');
  const [pasted, setPasted] = useState('');
  const [goldens, setGoldens] = useState<{ filename: string; content: string }[]>([]);
  const [goldenName, setGoldenName] = useState<string>('');
  const [uploadName, setUploadName] = useState<string | null>(null);
  const [uploadText, setUploadText] = useState('');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [busyUpload, setBusyUpload] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.goldenPrds().then(setGoldens).catch(() => setGoldens([]));
  }, []);

  const handleFile = useCallback(async (file: File) => {
    setBusyUpload(true);
    setUploadError(null);
    try {
      const res = await api.upload(file);
      setUploadText(res.text);
      setUploadName(res.filename);
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : '文件读取失败');
      setUploadText('');
      setUploadName(null);
    } finally {
      setBusyUpload(false);
    }
  }, []);

  const canRun =
    !running &&
    (source === 'paste'
      ? pasted.trim().length > 0
      : source === 'golden'
        ? goldenName !== ''
        : uploadText.trim().length > 0);

  const submit = () => {
    if (source === 'paste' && pasted.trim()) onRun({ prdText: pasted });
    else if (source === 'golden' && goldenName) {
      const golden = goldens.find((g) => g.filename === goldenName);
      if (golden) onRun({ prdText: golden.content, prdFilename: golden.filename });
    } else if (source === 'upload' && uploadText.trim()) {
      onRun({ prdText: uploadText, prdFilename: uploadName ?? undefined });
    }
  };

  return (
    <section className={`px-card ${styles.wrap}`}>
      <div className={styles.sources} role="tablist">
        {SOURCES.map((s) => (
          <button
            key={s.id}
            role="tab"
            aria-selected={source === s.id}
            className={`${styles.source} ${source === s.id ? styles.sourceActive : ''}`}
            onClick={() => setSource(s.id)}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className={styles.body}>
        {source === 'paste' && (
          <textarea
            className={styles.textarea}
            placeholder="把 PRD 全文粘贴到这里…（支持 Markdown）"
            value={pasted}
            onChange={(e) => setPasted(e.target.value)}
            rows={10}
          />
        )}

        {source === 'golden' && (
          <>
            <select
              className={styles.select}
              value={goldenName}
              onChange={(e) => setGoldenName(e.target.value)}
            >
              <option value="">选择一份内置 PRD…</option>
              {goldens.map((g) => (
                <option key={g.filename} value={g.filename}>
                  {g.filename}
                </option>
              ))}
            </select>
            {goldenName && (
              <details className={styles.preview}>
                <summary>预览</summary>
                <pre>{goldens.find((g) => g.filename === goldenName)?.content ?? ''}</pre>
              </details>
            )}
          </>
        )}

        {source === 'upload' && (
          <>
            <input
              ref={fileRef}
              type="file"
              accept=".pdf,.docx,.md,.markdown,.txt"
              className={styles.fileInput}
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void handleFile(f);
              }}
            />
            {busyUpload && <div className={styles.hint}>解析中…</div>}
            {uploadName && (
              <div className={styles.uploadOk}>
                ✅ 已读取 {uploadText.length} 字 · 来自 {uploadName}
              </div>
            )}
            {uploadError && <div className={styles.uploadErr}>📛 文件读取失败：{uploadError}</div>}
            <div className={styles.hint}>支持 PDF / Word(.docx) / Markdown / TXT，单文件上限 2 MB</div>
          </>
        )}
      </div>

      <div className={styles.actions}>
        <PixelButton variant="primary" onClick={submit} disabled={!canRun}>
          开始评审 ▶
        </PixelButton>
        {quotaError && <span className={styles.quotaErr}>{quotaError}</span>}
      </div>
    </section>
  );
}
