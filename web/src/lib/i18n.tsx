/** i18n — bilingual UI (中文/EN) with template interpolation.

   Language is persisted in localStorage. The review API receives the
   active language so the VERDICT matches the UI chrome: in zh mode the
   verdict is Chinese regardless of the PRD's language, while evidence
   quotes always stay verbatim in the PRD's original wording.
*/

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

export type Lang = 'zh' | 'en';

const zh = {
  // nav / status
  'nav.review': '评审',
  'nav.skills': 'Skill 库',
  'nav.ablation': '消融实验',
  'status.connecting': '连接中…',
  'status.local': '本地模式 · {model}',
  'status.quota': '今日剩余 {a}/{b} 次',

  // hero / composer
  'hero.kicker': '评审工作台',
  'hero.title': '把 PRD 放进来，先看风险，再看证据。',
  'hero.hint': '支持粘贴内容、选择示例或上传 PDF / Word 文档。',
  'composer.paste': '粘贴文本',
  'composer.golden': '选择内置 PRD',
  'composer.upload': '上传文件',
  'composer.placeholder': '把 PRD 全文粘贴到这里…（支持 Markdown）',
  'composer.goldenSelect': '选择一份内置 PRD…',
  'composer.preview': '预览',
  'composer.parsing': '解析中…',
  'composer.uploadOk': '✅ 已读取 {n} 字 · 来自 {f}',
  'composer.uploadErr': '📛 文件读取失败：{e}',
  'composer.uploadHint': '支持 PDF / Word(.docx) / Markdown / TXT，单文件上限 2 MB',
  'composer.run': '开始评审 ▶',
  'quota.global': '🛑 今日 demo 额度已用尽，请明天再试。',
  'quota.ip': '⏳ 本 IP 本小时已达上限，请稍后再试。',
  'quota.startFailed': '启动评审失败',

  // run deck
  'deck.title': '评审擂台',
  'deck.submitting': '提交评审…',
  'deck.stage1': 'Intake · 抽取 claim',
  'deck.stage2': '4 个 Critic 评审中',
  'deck.stage3': '智能体互辩',
  'deck.stage4': 'Supervisor 裁决中',
  'deck.stage5': '完成',
  'deck.idle': '待命',
  'deck.reasoning': '推理中',
  'deck.awaitingVerdict': '等待裁决',
  'deck.verdictDone': '裁决完成',
  'deck.scan1': '扫描依赖清单…',
  'deck.scan2': '核对 SKILL 库匹配…',
  'deck.scan3': '逐条 claim 交叉审阅…',
  'deck.scan4': '标记证据行号…',
  'deck.scan5': '收敛判定准备中…',
  'deck.clear': '评审完成 · 已存档',
  'deck.viewResults': '查看结果 ▼',
  'deck.reasoningLabel': '推理',
  'deck.reasoningConverged': '推理 · 第 {r} 轮收敛',
  'deck.reasoningDone': '（完成）',
  'deck.reasoningProgress': '…',
  'log.intake': 'INTAKE 已启动 · 解析 PRD 全文',
  'log.arena': '4 位 CRITIC 进入评审擂台',
  'log.critics': 'CRITIC 集结完毕 · 共 {n} 条 finding',
  'log.converged': '互辩 ROUND {r} · 收敛 ✓',
  'log.notConverged': '互辩 ROUND {r} · 达到最大轮数',
  'log.supervisor': 'SUPERVISOR 开始推理…',
  'log.verdict': '裁决已生成 · 写入档案…',
  'log.done': 'RUN 存档完成',

  // results
  'results.label': '评审结果',
  'results.clear': '✕ 清空',
  'results.exportMd': '导出 .md',
  'results.print': '打印 / PDF',
  'results.loadFail': '无法加载这份历史评审',
  'reconnect.banner': '📡 信号丢失 · 正在重连…',
  'verdict.kicker': 'Supervisor 裁决',
  'verdict.p0': 'P0 阻断项',
  'verdict.p1': 'P1 关注项',
  'verdict.p2': 'P2 建议',
  'verdict.none': '—— 暂无 ——',
  'verdict.conflicts': '分歧裁决',
  'critics.heading': 'Critic 评审结果',
  'critics.none': '此 Critic 暂无发现',
  'critics.thinkingDone': '推理（完成）',
  'cross.heading': '🔀 智能体互辩 · {n} 条记录',
  'cross.converged': '✅ 第 {r} 轮收敛',
  'cross.notConverged': '⚠️ 达到最大轮数（{r}）仍未收敛',
  'cross.none': '无互辩 —— 各 Critic 均认可其他人的发现',
  'cross.round': '第 {r} 轮 —— {n} 条互辩',

  // critique card
  'critique.evidence': '原文依据',
  'critique.fix': '建议改进',
  'critique.accept': '✓ 采纳',
  'critique.reject': '✗ 误报',
  'critique.accepted': '已记录为 ✓ 采纳',
  'critique.rejected': '已标记为误报',
  'critique.discuss': '💬 继续追问',
  'critique.discussClose': '💬 收起追问',
  'critique.you': '你',
  'critique.thinking': '思考中',
  'critique.discussFail': '追问失败',
  'critique.cap': '🛑 已达到追问上限（{n} 轮）。如需继续请关闭后重开。',
  'critique.placeholder': '继续追问 {c}…',
  'critique.send': '发送',

  // history
  'history.heading': '历史评审 · {n}',
  'history.loadFail': '无法加载历史记录',
  'history.loading': '加载中…',
  'history.empty': '还没跑过评审',
  'history.emptyHint': '点上方「开始评审」试一下',
  'history.custom': '自定义 PRD',
  'history.noP': '无 P 项',
  'history.delete': '🗑',
  'history.confirm': '删除',
  'history.cancel': '取消',

  // skills
  'skills.heading': 'Skill 库',
  'skills.count': '{n} 个 Skill 启用中',
  'skills.empty': 'Skill 库为空',
  'skills.emptyHint': '评审跑起来后，采纳反馈会塑造 Skill 库',
  'skills.select': '选择一个 Skill 查看详情',
  'skills.usage': '已应用 {n} 次',
  'skills.tech': '技术细节',
  'skills.md': '查看 SKILL.md',
  'skills.techMeta': 'v{v} · 由 {w} 创建 · 注入到 {r}',
  'skills.loadFail': '加载失败',
  'skills.deprecate': '🗑 停用',
  'distill.heading': 'Skill 提炼',
  'distill.sub': '从历史评审中挖掘重复模式',
  'distill.mining': '挖掘中…',
  'distill.run': '🔍 提炼 Skill',
  'distill.none': '暂未发现稳定的新 Skill 候选',
  'distill.found': '发现 {n} 个候选 Skill',
  'distill.fail': '提炼失败',
  'distill.empty': '暂无待审议的 Skill 提案',
  'distill.emptyHint': '点击「提炼 Skill」，系统会跨 PRD 挖掘重复出现的盲点模式，待你确认后加入 Skill 库。',
  'proposal.caption': '在 {n} 份不同 PRD 中重复出现 · 注入到 {r}',
  'proposal.evidence': '📎 证据 ({n})',
  'proposal.md': '📄 SKILL.md',
  'proposal.approve': '✅ 采纳',
  'proposal.reject': '❌ 驳回',
  'proposal.saveEdit': '✏️ 保存修改',
  'proposal.fail': '操作失败',

  // ablation
  'ablation.heading': '消融实验',
  'ablation.intro': '通过在多种检索条件下重跑每份 PRD 并对照预埋缺陷集打分，量化 Skill 库对系统的贡献。',
  'ablation.empty': '尚无消融报告',
  'ablation.emptyHint': '点击下方「重新运行消融实验」，或命令行运行 python -m src.eval --quick。快速模式约需 1 分钟。',
  'ablation.rerun': '重新运行消融实验',
  'ablation.quick': '快速模式（每格运行 1 次）',
  'ablation.running': '运行中…（约 1 分钟）',
  'ablation.runBtn': '▶️ 重新运行',
  'ablation.headline': '核心对比：ON vs OFF',
  'ablation.recall': '缺陷召回率',
  'ablation.precision': 'Precision',
  'ablation.latency': '平均耗时 (秒)',
  'ablation.cost': '平均成本 ($)',
  'ablation.delta': '{d} vs OFF',
  'ablation.table': '对比表',
  'ablation.metric': '指标',
  'ablation.rowRecall': '缺陷召回率',
  'ablation.rowPrecision': 'Precision',
  'ablation.rowStructure': '结构合规率',
  'ablation.rowDependency': '依赖识别召回率',
  'ablation.rowContradiction': '矛盾检测召回率',
  'ablation.rowSeverity': 'Severity F1',
  'ablation.rowActionability': '可执行性',
  'ablation.rowLatency': '平均耗时 (秒)',
  'ablation.rowCost': '平均成本 ($)',
  'ablation.rowCritiques': '单次产出数',
  'ablation.charts': '各实验组对比图',
  'ablation.meta': '生成于 {ts} · PRD: {n} 份 · 每组运行: {r}',
  'ablation.loadFail': '加载失败',
  'ablation.startFail': '启动失败',
  'ablation.fail': '消融失败',
  'ablation.disclaimer': '数据源：OpenAI gpt-4o-mini（Critics + Supervisor 同模型，supervisor 升级到 gpt-4o 为后续工作）· 完整方法论见 README。',
  'ablation.seed': '种子 Skill',
  'ablation.learned': '种子 + 自学习',

  // export (markdown report)
  'export.title': 'PRD 评审报告',
  'export.subtitle': 'Supervisor 裁决',
  'export.executive': '核心结论',
  'export.findings': 'Critic 发现',
  'export.conflicts': '分歧裁决',
  'export.evidence': '原文依据',
  'export.fix': '建议改进',
  'export.by': '评审人',
  'export.generated': '由 PIXEL·PRD 生成',
} as const;

const en: Record<keyof typeof zh, string> = {
  'nav.review': 'Review',
  'nav.skills': 'Skill Library',
  'nav.ablation': 'Ablation',
  'status.connecting': 'Connecting…',
  'status.local': 'Local mode · {model}',
  'status.quota': '{a}/{b} runs left today',

  'hero.kicker': 'Review Desk',
  'hero.title': 'Drop a PRD in. See the risks, then the evidence.',
  'hero.hint': 'Paste text, pick a sample, or upload a PDF / Word doc.',
  'composer.paste': 'Paste',
  'composer.golden': 'Sample PRD',
  'composer.upload': 'Upload',
  'composer.placeholder': 'Paste the full PRD here… (Markdown supported)',
  'composer.goldenSelect': 'Pick a sample PRD…',
  'composer.preview': 'Preview',
  'composer.parsing': 'Parsing…',
  'composer.uploadOk': '✅ Read {n} chars from {f}',
  'composer.uploadErr': '📛 Read failed: {e}',
  'composer.uploadHint': 'PDF / Word(.docx) / Markdown / TXT, 2 MB max',
  'composer.run': 'Start Review ▶',
  'quota.global': '🛑 Demo quota exhausted for today — try again tomorrow.',
  'quota.ip': '⏳ Hourly limit for this IP reached — try again later.',
  'quota.startFailed': 'Failed to start review',

  'deck.title': 'Review Arena',
  'deck.submitting': 'Submitting…',
  'deck.stage1': 'Intake · extracting claims',
  'deck.stage2': '4 critics reviewing',
  'deck.stage3': 'Cross-examination',
  'deck.stage4': 'Supervisor deliberating',
  'deck.stage5': 'Complete',
  'deck.idle': 'Standby',
  'deck.reasoning': 'Reasoning',
  'deck.awaitingVerdict': 'Awaiting verdict',
  'deck.verdictDone': 'Verdict delivered',
  'deck.scan1': 'Scanning dependencies…',
  'deck.scan2': 'Matching SKILL library…',
  'deck.scan3': 'Cross-reviewing claims…',
  'deck.scan4': 'Tagging evidence lines…',
  'deck.scan5': 'Preparing convergence check…',
  'deck.clear': 'Review complete · archived',
  'deck.viewResults': 'View Results ▼',
  'deck.reasoningLabel': 'Reasoning',
  'deck.reasoningConverged': 'Reasoning · round {r} converged',
  'deck.reasoningDone': ' (done)',
  'deck.reasoningProgress': '…',
  'log.intake': 'INTAKE started · parsing PRD',
  'log.arena': '4 CRITICS enter the arena',
  'log.critics': 'CRITICS report in · {n} findings',
  'log.converged': 'Cross-exam ROUND {r} · converged ✓',
  'log.notConverged': 'Cross-exam ROUND {r} · max rounds reached',
  'log.supervisor': 'SUPERVISOR starts reasoning…',
  'log.verdict': 'Verdict generated · archiving…',
  'log.done': 'Run archived',

  'results.label': 'Review Results',
  'results.clear': '✕ Clear',
  'results.exportMd': 'Export .md',
  'results.print': 'Print / PDF',
  'results.loadFail': 'Could not load this archived review',
  'reconnect.banner': '📡 Signal lost · reconnecting…',
  'verdict.kicker': 'Supervisor Verdict',
  'verdict.p0': 'P0 Blockers',
  'verdict.p1': 'P1 Concerns',
  'verdict.p2': 'P2 Suggestions',
  'verdict.none': '—— none ——',
  'verdict.conflicts': 'Conflict Resolutions',
  'critics.heading': 'Critic Findings',
  'critics.none': 'No findings from this critic',
  'critics.thinkingDone': 'Reasoning (done)',
  'cross.heading': '🔀 Cross-examination · {n} records',
  'cross.converged': '✅ Converged at round {r}',
  'cross.notConverged': '⚠️ Max rounds reached ({r}), not converged',
  'cross.none': 'No challenges — every critic accepted the others’ findings',
  'cross.round': 'Round {r} —— {n} challenges',

  'critique.evidence': 'Evidence',
  'critique.fix': 'Suggested Fix',
  'critique.accept': '✓ Accept',
  'critique.reject': '✗ Noise',
  'critique.accepted': 'Recorded as ✓ accepted',
  'critique.rejected': 'Marked as noise',
  'critique.discuss': '💬 Follow up',
  'critique.discussClose': '💬 Close',
  'critique.you': 'You',
  'critique.thinking': 'Thinking',
  'critique.discussFail': 'Follow-up failed',
  'critique.cap': '🛑 Follow-up limit reached ({n} rounds). Close and reopen to continue.',
  'critique.placeholder': 'Follow up with {c}…',
  'critique.send': 'Send',

  'history.heading': 'History · {n}',
  'history.loadFail': 'Could not load history',
  'history.loading': 'Loading…',
  'history.empty': 'No reviews yet',
  'history.emptyHint': 'Hit “Start Review” above to try one',
  'history.custom': 'Custom PRD',
  'history.noP': 'no P items',
  'history.delete': '🗑',
  'history.confirm': 'Delete',
  'history.cancel': 'Cancel',

  'skills.heading': 'Skill Library',
  'skills.count': '{n} skills enabled',
  'skills.empty': 'Skill library is empty',
  'skills.emptyHint': 'Reviews and your feedback shape the library',
  'skills.select': 'Pick a skill to see details',
  'skills.usage': 'Applied {n} times',
  'skills.tech': 'Tech details',
  'skills.md': 'View SKILL.md',
  'skills.techMeta': 'v{v} · created by {w} · injected into {r}',
  'skills.loadFail': 'Load failed',
  'skills.deprecate': '🗑 Deprecate',
  'distill.heading': 'Skill Distillation',
  'distill.sub': 'Mines recurring patterns from past reviews',
  'distill.mining': 'Mining…',
  'distill.run': '🔍 Distill Skills',
  'distill.none': 'No stable new skill candidates yet',
  'distill.found': 'Found {n} candidate skills',
  'distill.fail': 'Distillation failed',
  'distill.empty': 'No proposals awaiting review',
  'distill.emptyHint': 'Hit “Distill Skills” to mine recurring blind-spot patterns across PRDs; you approve them before they join the library.',
  'proposal.caption': 'Recurred across {n} distinct PRDs · injected into {r}',
  'proposal.evidence': '📎 Evidence ({n})',
  'proposal.md': '📄 SKILL.md',
  'proposal.approve': '✅ Approve',
  'proposal.reject': '❌ Reject',
  'proposal.saveEdit': '✏️ Save edit',
  'proposal.fail': 'Action failed',

  'ablation.heading': 'Ablation Lab',
  'ablation.intro': 'Re-runs every PRD under several retrieval conditions and scores against planted defects to quantify the Skill library’s contribution.',
  'ablation.empty': 'No ablation report yet',
  'ablation.emptyHint': 'Hit “Re-run ablation” below, or run `python -m src.eval --quick`. Quick mode takes ~1 minute.',
  'ablation.rerun': 'Re-run Ablation',
  'ablation.quick': 'Quick mode (1 run per cell)',
  'ablation.running': 'Running… (~1 minute)',
  'ablation.runBtn': '▶️ Re-run',
  'ablation.headline': 'Headline: ON vs OFF',
  'ablation.recall': 'Defect Recall',
  'ablation.precision': 'Precision',
  'ablation.latency': 'Avg latency (s)',
  'ablation.cost': 'Avg cost ($)',
  'ablation.delta': '{d} vs OFF',
  'ablation.table': 'Comparison Table',
  'ablation.metric': 'Metric',
  'ablation.rowRecall': 'Defect Recall',
  'ablation.rowPrecision': 'Precision',
  'ablation.rowStructure': 'Structure Compliance',
  'ablation.rowDependency': 'Dependency Recall',
  'ablation.rowContradiction': 'Contradiction Recall',
  'ablation.rowSeverity': 'Severity F1',
  'ablation.rowActionability': 'Actionability',
  'ablation.rowLatency': 'Avg latency (s)',
  'ablation.rowCost': 'Avg cost ($)',
  'ablation.rowCritiques': 'Critiques per run',
  'ablation.charts': 'Per-treatment Comparison',
  'ablation.meta': 'Generated {ts} · PRDs: {n} · runs per cell: {r}',
  'ablation.loadFail': 'Load failed',
  'ablation.startFail': 'Start failed',
  'ablation.fail': 'Ablation failed',
  'ablation.disclaimer': 'Data source: OpenAI gpt-4o-mini (critics + supervisor share the model; upgrading the supervisor to gpt-4o is future work) · full methodology in README.',
  'ablation.seed': 'Seed skills',
  'ablation.learned': 'Seed + learned',

  'export.title': 'PRD Review Report',
  'export.subtitle': 'Supervisor Verdict',
  'export.executive': 'Executive Summary',
  'export.findings': 'Critic Findings',
  'export.conflicts': 'Conflict Resolutions',
  'export.evidence': 'Evidence',
  'export.fix': 'Suggested Fix',
  'export.by': 'Reviewer',
  'export.generated': 'Generated by PIXEL·PRD',
};

export type TKey = keyof typeof zh;

const DICTS: Record<Lang, Record<string, string>> = { zh, en };

interface LangApi {
  lang: Lang;
  setLang: (l: Lang) => void;
  t: (key: string, vars?: Record<string, string | number>) => string;
}

const LangContext = createContext<LangApi>({
  lang: 'zh',
  setLang: () => {},
  t: (key) => key,
});

const STORAGE_KEY = 'px-lang';

export function LangProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<Lang>(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved === 'en' ? 'en' : 'zh';
    } catch {
      return 'zh';
    }
  });

  const setLang = useCallback((l: Lang) => {
    try {
      localStorage.setItem(STORAGE_KEY, l);
    } catch {
      /* private mode — session-only */
    }
    setLangState(l);
  }, []);

  const t = useCallback(
    (key: string, vars?: Record<string, string | number>) => {
      let s = DICTS[lang][key] ?? DICTS.zh[key] ?? key;
      if (vars) {
        for (const [k, v] of Object.entries(vars)) {
          s = s.replaceAll(`{${k}}`, String(v));
        }
      }
      return s;
    },
    [lang],
  );

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <LangContext.Provider value={value}>{children}</LangContext.Provider>;
}

export function useT(): LangApi {
  return useContext(LangContext);
}
