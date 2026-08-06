import { useState, useRef, useEffect, useCallback, useMemo } from 'react'
import ReactMarkdown from 'react-markdown'
import {
  askStream, compareStream, submitFeedback, getCurrentUserId,
  AskResponse, ComparisonResult, StreamEvent, GenieStep, GenieSpaceInfo,
  CacheEntry, getLandingData, SampleQuestion,
} from '../api'
import './ChatPage.css'

const STORAGE_KEY_MESSAGES = 'genie-chat-messages';
const STORAGE_KEY_SESSION = 'genie-chat-session';
const STORAGE_KEY_TITLE = 'genie-chat-title';

interface ThinkingStep {
  node: string;
  label: string;
  detail: string;
  elapsed_ms: number;
}

interface StreamingSubResult {
  space_id: string;
  space_title: string;
  sub_question: string;
  sql?: string;
  description?: string;
  columns?: string[];
  data?: any[][];
  row_count?: number;
  cache_hit?: boolean;
  index: number;
}

interface SupervisorPlan {
  agent: string;
  agent_id: string;
  task: string;
  step: number;
}

interface ComparisonData {
  responseA?: AskResponse;
  responseB?: AskResponse;
  thinkingA?: ThinkingStep[];
  thinkingB?: ThinkingStep[];
  summary?: ComparisonResult;
  phase: 'pending' | 'running_a' | 'running_b' | 'done';
}

interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
  response?: AskResponse;
  feedbackGiven?: number;
  streaming?: boolean;
  typing?: boolean;
  streamingSubResults?: StreamingSubResult[];
  supervisorPlan?: SupervisorPlan[];
  thinkingSteps?: ThinkingStep[];
  comparison?: ComparisonData;
  // Set when the cache could not be reached, so the answer came from Genie
  // because of an outage rather than an ordinary miss.
  cacheUnavailable?: boolean;
}

interface PromptGroup<T> {
  key: string;
  title: string;
  items: T[];
}

function groupCachedQuestions(entries: CacheEntry[], spaces: GenieSpaceInfo[]): PromptGroup<CacheEntry>[] {
  const titleById = new Map(spaces.map(space => [space.space_id, space.title]));
  const groups = new Map<string, PromptGroup<CacheEntry>>();

  for (const entry of entries) {
    if (!entry.query_text) continue;
    const key = entry.genie_space_id || 'unknown';
    const title = titleById.get(key) || entry.genie_space_id || 'Unknown Genie Space';
    if (!groups.has(key)) groups.set(key, { key, title, items: [] });
    groups.get(key)!.items.push(entry);
  }

  return orderPromptGroups(groups, spaces);
}

function groupSampleQuestions(items: SampleQuestion[], spaces: GenieSpaceInfo[]): PromptGroup<SampleQuestion>[] {
  const groups = new Map<string, PromptGroup<SampleQuestion>>();

  for (const item of items) {
    if (!item.question) continue;
    const key = item.space_id || item.space_title || 'unknown';
    const title = item.space_title || spaces.find(space => space.space_id === item.space_id)?.title || 'Unknown Genie Space';
    if (!groups.has(key)) groups.set(key, { key, title, items: [] });
    groups.get(key)!.items.push(item);
  }

  return orderPromptGroups(groups, spaces);
}

function orderPromptGroups<T>(groups: Map<string, PromptGroup<T>>, spaces: GenieSpaceInfo[]): PromptGroup<T>[] {
  const ordered: PromptGroup<T>[] = [];
  const used = new Set<string>();

  for (const space of spaces) {
    const group = groups.get(space.space_id) || groups.get(space.title);
    if (group) {
      ordered.push(group);
      used.add(group.key);
    }
  }

  for (const group of groups.values()) {
    if (!used.has(group.key)) ordered.push(group);
  }

  return ordered;
}

function loadMessages(): ChatMessage[] {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY_MESSAGES);
    if (!raw) return [];
    const msgs: ChatMessage[] = JSON.parse(raw);
    // Any messages that were mid-stream when the tab switched get finalized
    return msgs.map(m => m.streaming ? { ...m, streaming: false, typing: false } : m);
  } catch { return []; }
}

function loadSessionId(): string | undefined {
  return sessionStorage.getItem(STORAGE_KEY_SESSION) || undefined;
}

export default function ChatPage() {
  const [messages, setMessages] = useState<ChatMessage[]>(loadMessages);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>(loadSessionId);
  const [sessionTitle, setSessionTitle] = useState<string | undefined>(
    () => sessionStorage.getItem(STORAGE_KEY_TITLE) || undefined
  );
  const [userId, setUserId] = useState<string>('unknown');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const messagesRef = useRef<ChatMessage[]>(messages);

  // Genie Spaces + sample questions (loaded from config on mount)
  const [activeSpaces, setActiveSpaces] = useState<GenieSpaceInfo[]>([]);
  const [sampleQuestions, setSampleQuestions] = useState<SampleQuestion[]>([]);
  const [cachedQuestions, setCachedQuestions] = useState<CacheEntry[]>([]);
  const [promptsLoading, setPromptsLoading] = useState(true);

  useEffect(() => {
    getCurrentUserId().then(setUserId);
    getLandingData()
      .then(data => {
        setActiveSpaces(data.active_spaces);
        setSampleQuestions(data.sample_questions);
        setCachedQuestions(data.cache_entries.filter(e => e.query_text).slice(0, 12));
      })
      .catch(() => {
        setActiveSpaces([]);
        setSampleQuestions([]);
        setCachedQuestions([]);
      })
      .finally(() => setPromptsLoading(false));
  }, []);

  // Persist messages to sessionStorage whenever they change (skip mid-stream updates)
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const persistMessages = useCallback((msgs: ChatMessage[]) => {
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      // Only persist completed (non-streaming) messages
      const toSave = msgs.filter(m => !m.streaming);
      try { sessionStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(toSave)); } catch { /* quota */ }
    }, 300);
  }, []);

  useEffect(() => {
    messagesRef.current = messages;
    persistMessages(messages);
  }, [messages, persistMessages]);

  // On unmount: abort any in-flight stream and force-save current messages
  useEffect(() => {
    return () => {
      if (abortRef.current) {
        abortRef.current.abort();
        abortRef.current = null;
      }
      const current = messagesRef.current;
      const finalized = current.map(m =>
        m.streaming ? { ...m, streaming: false, typing: false } : m
      );
      try { sessionStorage.setItem(STORAGE_KEY_MESSAGES, JSON.stringify(finalized)); } catch { /* quota */ }
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (sessionId) sessionStorage.setItem(STORAGE_KEY_SESSION, sessionId);
    else sessionStorage.removeItem(STORAGE_KEY_SESSION);
  }, [sessionId]);

  useEffect(() => {
    if (sessionTitle) sessionStorage.setItem(STORAGE_KEY_TITLE, sessionTitle);
    else sessionStorage.removeItem(STORAGE_KEY_TITLE);
  }, [sessionTitle]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSend = async () => {
    if (!input.trim() || loading) return;
    const question = input.trim();
    setInput('');

    setMessages(prev => [...prev, { role: 'user', content: question }]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const assistantIdx = messages.length + 1;
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: '',
      streaming: true,
    }]);

    try {
      let receivedComplete = false;
      await askStream(
        question,
        (event: StreamEvent) => {
          setMessages(prev => {
            const updated = [...prev];
            const msg = { ...updated[assistantIdx] };

            switch (event.event) {
              case 'session':
                setSessionId(event.data.session_id);
                if (event.data.title) setSessionTitle(event.data.title);
                break;

              case 'status':
                if (event.data.step !== 'session') {
                  msg.content = event.data.message;
                }
                break;

              case 'rewrite':
                msg.content = `Rewritten: "${event.data.rewritten}"`;
                break;

              case 'intent':
                msg.content = event.data.message;
                if (event.data.plan) {
                  msg.supervisorPlan = event.data.plan as SupervisorPlan[];
                }
                break;

              case 'cache_hit':
              case 'cache_miss':
                msg.content = event.data.message;
                break;

              // The cache could not be reached at all. Distinct from a miss so
              // an outage is visible rather than looking like normal behaviour.
              case 'cache_unavailable':
                msg.content = event.data.message;
                msg.cacheUnavailable = true;
                break;

              case 'genie_step': {
                const isTerminal = ['COMPLETED', 'FAILED', 'CANCELLED'].includes(event.data.status);
                if (!isTerminal) {
                  msg.content = event.data.label;
                }
                break;
              }

              case 'sub_result': {
                const subs = [...(msg.streamingSubResults || [])];
                subs.push(event.data as StreamingSubResult);
                msg.streamingSubResults = subs;
                const sr = event.data as StreamingSubResult;
                msg.content = sr.description || `${sr.space_title}: ${sr.row_count ?? 0} rows`;
                break;
              }

              case 'sql':
                msg.content = 'SQL generated, fetching results...';
                break;

              case 'text_chunk':
                msg.content = event.data.full_text;
                msg.typing = true;
                break;

              case 'thinking': {
                const ts = [...(msg.thinkingSteps || [])];
                ts.push({
                  node: event.data.node,
                  label: event.data.label,
                  detail: event.data.detail,
                  elapsed_ms: event.data.elapsed_ms || 0,
                });
                msg.thinkingSteps = ts;
                break;
              }

              case 'complete': {
                receivedComplete = true;
                const resp = event.data as AskResponse;
                msg.streaming = false;
                msg.typing = false;
                msg.response = resp;
                if (resp.session_title) setSessionTitle(resp.session_title);
                if (resp.sql) {
                  msg.content = `Generated SQL query (${resp.row_count ?? 0} rows)`;
                } else if (resp.description) {
                  msg.content = resp.description;
                } else {
                  msg.content = 'No response generated';
                }
                break;
              }

              case 'error':
                msg.streaming = false;
                msg.typing = false;
                msg.content = `Error: ${event.data?.message || 'Something went wrong'}`;
                receivedComplete = true;
                break;
            }

            updated[assistantIdx] = msg;
            return updated;
          });
        },
        sessionId,
        userId,
        controller.signal,
      );
      if (!receivedComplete) {
        setMessages(prev => {
          const updated = [...prev];
          const msg = { ...updated[assistantIdx] };
          msg.streaming = false;
          msg.typing = false;
          if (!msg.content || msg.content === '') {
            msg.content = 'Stream ended without a response. Check the MLflow trace for details.';
          }
          updated[assistantIdx] = msg;
          return updated;
        });
      }
    } catch (err: any) {
      if (err.name === 'AbortError') {
        setMessages(prev => {
          const updated = [...prev];
          const msg = { ...updated[assistantIdx] };
          msg.streaming = false;
          msg.typing = false;
          msg.content = msg.content || 'Stopped';
          updated[assistantIdx] = msg;
          return updated;
        });
      } else {
        setMessages(prev => {
          const updated = [...prev];
          updated[assistantIdx] = {
            role: 'assistant',
            content: `Error: ${err.message || 'Something went wrong'}`,
            streaming: false,
          };
          return updated;
        });
      }
    }
    abortRef.current = null;
    setLoading(false);
  };

  const handleStop = () => {
    if (abortRef.current) {
      abortRef.current.abort();
    }
  };

  const handleCompare = async () => {
    if (!input.trim() || loading) return;
    const question = input.trim();
    setInput('');

    setMessages(prev => [...prev, { role: 'user', content: `[A/B Compare] ${question}` }]);
    setLoading(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const assistantIdx = messages.length + 1;
    setMessages(prev => [...prev, {
      role: 'assistant',
      content: 'Running both pipelines in parallel...',
      streaming: true,
      comparison: { phase: 'running_a', thinkingA: [], thinkingB: [] },
    }]);

    try {
      await compareStream(
        question,
        (event: StreamEvent) => {
          setMessages(prev => {
            const updated = [...prev];
            const msg = { ...updated[assistantIdx] };
            const cmp = { ...(msg.comparison || { phase: 'running_a' as const, thinkingA: [], thinkingB: [] }) };
            const ev = event.event;

            if (ev.startsWith('a_')) {
              const inner = ev.slice(2);
              if (inner === 'thinking') {
                cmp.thinkingA = [...(cmp.thinkingA || []), {
                  node: event.data.node, label: event.data.label,
                  detail: event.data.detail, elapsed_ms: event.data.elapsed_ms || 0,
                }];
              } else if (inner === 'complete') {
                cmp.responseA = event.data as AskResponse;
              }
            } else if (ev.startsWith('b_')) {
              const inner = ev.slice(2);
              if (inner === 'thinking') {
                cmp.thinkingB = [...(cmp.thinkingB || []), {
                  node: event.data.node, label: event.data.label,
                  detail: event.data.detail, elapsed_ms: event.data.elapsed_ms || 0,
                }];
              } else if (inner === 'complete') {
                cmp.responseB = event.data as AskResponse;
              }
            } else if (ev === 'comparison') {
              cmp.summary = event.data as ComparisonResult;
              cmp.phase = 'done';
              msg.streaming = false;
              msg.content = 'A/B comparison complete';
            } else if (ev === 'error') {
              msg.streaming = false;
              msg.content = `Error: ${event.data?.message || 'Comparison failed'}`;
              cmp.phase = 'done';
            }

            msg.comparison = cmp;
            updated[assistantIdx] = msg;
            return updated;
          });
        },
        userId,
        controller.signal,
      );
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setMessages(prev => {
          const updated = [...prev];
          updated[assistantIdx] = {
            role: 'assistant', content: `Error: ${err.message}`, streaming: false,
            comparison: { phase: 'done' as const },
          };
          return updated;
        });
      }
    }
    abortRef.current = null;
    setLoading(false);
  };

  const safeActiveSpaces = Array.isArray(activeSpaces) ? activeSpaces : [];

  const cachedQuestionsBySpace = useMemo(
    () => groupCachedQuestions(cachedQuestions, safeActiveSpaces),
    [cachedQuestions, safeActiveSpaces],
  );
  const sampleQuestionsBySpace = useMemo(
    () => groupSampleQuestions(sampleQuestions, safeActiveSpaces),
    [sampleQuestions, safeActiveSpaces],
  );

  const sessionStats = useMemo(() => {
    const completed = messages.filter(m => m.role === 'assistant' && m.response);
    const total = completed.length;
    const hits = completed.filter(m => m.response!.cache_status === 'hit').length;
    const timeSaved = completed.reduce((sum, m) => {
      const r = m.response!;
      if (r.cache_status === 'hit' && r.genie_latency_ms != null) {
        return sum + Math.max(0, r.genie_latency_ms - r.latency_ms);
      }
      return sum;
    }, 0);
    return { total, hits, timeSaved };
  }, [messages]);

  const handleFeedback = async (idx: number, rating: number) => {
    const msg = messages[idx];
    if (!msg.response) return;

    await submitFeedback(msg.response.trace_id, rating, userId);
    setMessages(prev => prev.map((m, i) => i === idx ? { ...m, feedbackGiven: rating } : m));
  };

  const handleNewSession = () => {
    setMessages([]);
    setSessionId(undefined);
    setSessionTitle(undefined);
    sessionStorage.removeItem(STORAGE_KEY_MESSAGES);
    sessionStorage.removeItem(STORAGE_KEY_SESSION);
    sessionStorage.removeItem(STORAGE_KEY_TITLE);
  };

  return (
    <div className="chat-page">
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>{sessionTitle || 'Chat with Genie'}</h1>
            <p>Ask data questions with semantic caching and user memory</p>
          </div>
          <button className="btn" onClick={handleNewSession}>New Session</button>
        </div>
      </div>

      {/* Genie Spaces (linked to Genie rooms) */}
      {safeActiveSpaces.length > 0 && (
        <div className="spaces-bar">
          <div className="spaces-bar-header">
            <span className="spaces-bar-label">
              <GenieIcon /> Genie Spaces
            </span>
            <div className="spaces-chips">
              {safeActiveSpaces.map(s => (
                s.genie_room_url ? (
                  <a
                    key={s.space_id}
                    href={s.genie_room_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="space-chip-link"
                    title={s.description || s.title}
                    onClick={(e) => {
                      e.preventDefault();
                      window.open(s.genie_room_url!, '_blank', 'noopener,noreferrer');
                    }}
                  >
                    <span className="space-chip-title">{s.title}</span>
                    <ExternalLinkMini />
                  </a>
                ) : (
                  <span key={s.space_id} className="space-chip active" title={s.description || s.title}>
                    {s.title}
                  </span>
                )
              ))}
            </div>
          </div>
        </div>
      )}

      <div className="chat-container">
        {sessionStats.total > 0 && (
          <div className="session-stats-bar">
            <span className="stat-item">
              <span className="stat-value">{sessionStats.total}</span> queries
            </span>
            <span className="stat-divider">|</span>
            <span className="stat-item stat-hits">
              <span className="stat-value">{sessionStats.hits}</span> cache hits
              {sessionStats.total > 0 && (
                <span className="stat-pct">
                  ({Math.round((sessionStats.hits / sessionStats.total) * 100)}%)
                </span>
              )}
            </span>
            {sessionStats.timeSaved > 0 && (
              <>
                <span className="stat-divider">|</span>
                <span className="stat-item stat-saved">
                  ~<span className="stat-value">{(sessionStats.timeSaved / 1000).toFixed(1)}s</span> saved
                </span>
              </>
            )}
          </div>
        )}
        <div className="messages">
          {messages.length === 0 && (
            <div className="empty-state">
              <div className="empty-icon">💬</div>
              <h3>Ask a question about your data</h3>
              <p>
                Powered by semantic caching — first queries go through Genie,
                similar follow-ups are served instantly from cache.
              </p>
              {safeActiveSpaces.length > 0 && (
                <div className="empty-spaces">
                  {safeActiveSpaces.map(s => (
                    <span key={s.space_id} className="empty-space-tag">{s.title}</span>
                  ))}
                </div>
              )}
              <div className="empty-prompt-sections">
                {promptsLoading && (
                  <div className="empty-prompts-loading">Loading demo prompts...</div>
                )}

                {cachedQuestionsBySpace.length > 0 && (
                  <div className="empty-prompt-section">
                    <div className="empty-prompt-section-title">Cached questions</div>
                    <div className="empty-space-groups">
                      {cachedQuestionsBySpace.map(group => (
                        <div key={group.key} className="empty-space-group">
                          <div className="empty-space-group-title">{group.title}</div>
                          <div className="empty-examples">
                            {group.items.map((item) => (
                              <button
                                key={item.id}
                                className="empty-example-card"
                                onClick={() => { setInput(item.query_text); }}
                              >
                                <span className="empty-example-arrow">→</span>
                                {item.query_text}
                                <span className="empty-example-badge badge-cached">⚡ Cached</span>
                              </button>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="empty-prompt-section">
                  <div className="empty-prompt-section-title">Sample questions</div>
                  <div className="empty-space-groups">
                    {sampleQuestionsBySpace.length > 0 ? sampleQuestionsBySpace.map(group => (
                      <div key={group.key} className="empty-space-group">
                        <div className="empty-space-group-title">{group.title}</div>
                        <div className="empty-examples">
                          {group.items.map((item, i) => (
                            <button
                              key={`${group.key}-${i}`}
                              className="empty-example-card"
                              onClick={() => { setInput(item.question); }}
                            >
                              <span className="empty-example-arrow">→</span>
                              {item.question}
                              <span className="empty-example-badge badge-space">Genie</span>
                            </button>
                          ))}
                        </div>
                      </div>
                    )) : !promptsLoading && (
                      <button
                        className="empty-example-card"
                        onClick={() => { setInput('What data is available?'); }}
                      >
                        <span className="empty-example-arrow">→</span>
                        What data is available?
                      </button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          )}

          {messages.map((msg, idx) => {
            const cacheClass = msg.role === 'assistant' && msg.response
              ? msg.response.cache_status === 'hit' ? 'msg-cache-hit' : 'msg-cache-miss'
              : '';
            return (
            <div key={idx} className={`message ${msg.role} ${cacheClass}`}>
              <div className="message-content">
                {/* A/B Comparison card */}
                {msg.comparison && (
                  <ComparisonCard comparison={msg.comparison} streaming={!!msg.streaming} statusText={msg.content} />
                )}

                {/* Normal response flow (skip if comparison mode) */}
                {!msg.comparison && msg.thinkingSteps && msg.thinkingSteps.length > 0 && (
                  <ThinkingPanel steps={msg.thinkingSteps} streaming={!!msg.streaming} />
                )}

                {/* Supervisor plan during streaming */}
                {!msg.comparison && msg.streaming && msg.supervisorPlan && msg.supervisorPlan.length > 1 && (
                  <div className="streaming-plan">
                    <div className="plan-header">Supervisor Plan</div>
                    <div className="plan-tasks">
                      {msg.supervisorPlan.map((t, i) => {
                        const isDone = msg.streamingSubResults?.some(sr => sr.space_title === t.agent);
                        return (
                          <div key={i} className={`plan-task ${isDone ? 'done' : ''}`}>
                            <span className="plan-step">Step {t.step}</span>
                            <span className="plan-agent">{t.agent}</span>
                            <span className="plan-question">{t.task}</span>
                            {isDone && <span className="plan-check">✓</span>}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Progressive sub-results as each space completes */}
                {!msg.comparison && msg.streaming && msg.streamingSubResults && msg.streamingSubResults.length > 0 && (
                  <div className="streaming-sub-results">
                    {msg.streamingSubResults.map((sr, i) => (
                      <div key={i} className={`streaming-sub-result ${sr.cache_hit ? 'cache-hit' : ''}`}>
                        <div className="ssr-header">
                          <span className="ssr-space">{sr.cache_hit ? '⚡' : '🏠'} {sr.space_title}</span>
                          <span className="ssr-rows">{sr.row_count ?? 0} rows</span>
                        </div>
                        <div className="ssr-question">{sr.sub_question}</div>
                        {sr.description && (
                          <div className="ssr-description markdown-content">
                            <ReactMarkdown>{sr.description}</ReactMarkdown>
                          </div>
                        )}
                        {sr.columns && sr.data && sr.data.length > 0 && (
                          <div className="ssr-table-wrapper">
                            <table className="data-table compact">
                              <thead>
                                <tr>{sr.columns.map((c, ci) => <th key={ci}>{c}</th>)}</tr>
                              </thead>
                              <tbody>
                                {sr.data.slice(0, 5).map((row, ri) => (
                                  <tr key={ri}>{row.map((cell: any, ci: number) => <td key={ci}>{cell?.toString() ?? ''}</td>)}</tr>
                                ))}
                              </tbody>
                            </table>
                            {sr.data.length > 5 && (
                              <div className="ssr-more">+ {sr.data.length - 5} more rows</div>
                            )}
                          </div>
                        )}
                        {sr.sql && <SqlCollapsible sql={sr.sql} label={`SQL (${sr.space_title})`} />}
                      </div>
                    ))}
                  </div>
                )}

                {/* Typing text (streamed word-by-word) */}
                {!msg.comparison && msg.streaming && msg.typing && (
                  <div className="message-text typing-text markdown-content">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                    <span className="typing-cursor" />
                  </div>
                )}

                {/* Final message text (shown when not streaming or when complete).
                    Hide when description exists (it's rendered in response-details to avoid duplication). */}
                {!msg.comparison && !msg.streaming && !(msg.response?.description && !msg.response?.sql) && (
                  <div className="message-text markdown-content">
                    <ReactMarkdown>{msg.content}</ReactMarkdown>
                  </div>
                )}

                {!msg.comparison && msg.response && (
                  <div className="response-details">
                    <ResponseMeta response={msg.response} />
                    {msg.response.cache_status === 'hit' && msg.response.rewritten_question && (
                      <div className="rewritten-inline">
                        Matched: <em>{msg.response.rewritten_question}</em>
                      </div>
                    )}

                    {/* LLM-generated description / summary — always visible */}
                    {msg.response.description && (
                      <div className="genie-text-response markdown-content">
                        <ReactMarkdown>{msg.response.description}</ReactMarkdown>
                      </div>
                    )}

                    {/* Query details: supervisor plan (collapsed) */}
                    {msg.response.supervisor_plan?.length ? (
                      <Collapsible
                        label="Query Details"
                        badge={msg.response.supervisor_plan.length > 1
                          ? `${msg.response.supervisor_plan.length} sub-tasks`
                          : undefined}
                      >
                        <div className="supervisor-plan">
                          <span className="supervisor-plan-label">Supervisor →</span>
                          {msg.response.supervisor_plan.map((t, i) => (
                            <span key={i} className="supervisor-plan-task">
                              <span className="plan-agent">{t.agent}</span>
                              {msg.response!.supervisor_plan!.length > 1 && (
                                <span className="plan-task-text" title={t.task}>{t.task}</span>
                              )}
                            </span>
                          ))}
                        </div>
                      </Collapsible>
                    ) : null}

                    {/* Multi-space sub-results — each space in a numbered card */}
                    {msg.response.sub_results && msg.response.sub_results.length > 1 && (
                      <div className="sub-results-section">
                        <div className="sub-results-divider">
                          <span className="sub-results-divider-text">Source Details</span>
                        </div>
                        <div className="sub-results-cards">
                          {msg.response.sub_results.map((sr, i) => (
                            <div key={i} className={`sub-result-card ${sr.cache_hit ? 'sub-card-hit' : 'sub-card-miss'}`}>
                              <div className="sub-card-header">
                                <span className="sub-card-step">Step {i + 1}</span>
                                <span className="sub-card-space">{sr.space_title}</span>
                                <span className={`sub-card-cache-badge ${sr.cache_hit ? 'badge-hit' : 'badge-miss'}`}>
                                  {sr.cache_hit ? '⚡ Cache Hit' : '🔮 Genie'}
                                </span>
                                {sr.row_count != null && (
                                  <span className="sub-card-rows">{sr.row_count} rows</span>
                                )}
                              </div>
                              <div className="sub-card-question">{sr.sub_question}</div>
                              {sr.description && (
                                <div className="sub-card-description markdown-content">
                                  <ReactMarkdown>{sr.description}</ReactMarkdown>
                                </div>
                              )}
                              {sr.sql && <SqlCollapsible sql={sr.sql} label="SQL" />}
                              {sr.columns && sr.data && sr.data.length > 0 && (
                                <DataTable columns={sr.columns} data={sr.data} />
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* Single-space SQL + data table (collapsed) */}
                    {msg.response.sql && !msg.response.sub_results && (
                      <SqlCollapsible sql={msg.response.sql} />
                    )}

                    {!msg.response.sub_results && msg.response.columns && msg.response.data && msg.response.data.length > 0 && (
                      <Collapsible label="Data Results" badge={`${msg.response.row_count ?? msg.response.data.length} rows`}>
                        <DataTable columns={msg.response.columns} data={msg.response.data} />
                      </Collapsible>
                    )}

                    {/* Memory context (collapsed) */}
                    {msg.response.memory_context && msg.response.memory_context.length > 0 && (
                      <Collapsible label="Memory Context" badge={`${msg.response.memory_context.length}`}>
                        <div className="context-items">
                          {msg.response.memory_context.map((c, i) => (
                            <span key={i} className="context-item">{c}</span>
                          ))}
                        </div>
                      </Collapsible>
                    )}

                    {/* Genie execution timeline (already collapsible) */}
                    {msg.response.genie_steps && msg.response.genie_steps.length > 0 && (
                      <GenieTimeline
                        steps={msg.response.genie_steps}
                        totalMs={msg.response.genie_latency_ms}
                      />
                    )}

                    {msg.response.follow_up_questions && msg.response.follow_up_questions.length > 0 && (
                      <div className="follow-up-section">
                        <div className="follow-up-divider">
                          <span className="follow-up-divider-label">Try asking</span>
                        </div>
                        <div className="follow-up-chips">
                          {msg.response.follow_up_questions.map((q, qi) => (
                            <button
                              key={qi}
                              className="follow-up-chip"
                              onClick={() => { setInput(q); }}
                              disabled={loading}
                            >
                              <span className="follow-up-arrow">→</span>
                              {q}
                            </button>
                          ))}
                        </div>
                      </div>
                    )}

                    <div className="feedback-bar">
                      {msg.feedbackGiven !== undefined ? (
                        <span className={`feedback-thanks ${msg.feedbackGiven === 1 ? 'thanks-positive' : 'thanks-negative'}`}>
                          {msg.feedbackGiven === 1 ? '👍' : '👎'} Thanks for your feedback
                        </span>
                      ) : (
                        <>
                          <span className="feedback-label">Was this helpful?</span>
                          <button className="btn-icon" onClick={() => handleFeedback(idx, 1)}>
                            <ThumbsUp />
                          </button>
                          <button className="btn-icon" onClick={() => handleFeedback(idx, -1)}>
                            <ThumbsDown />
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
            );
          })}

          <div ref={messagesEndRef} />
        </div>

        <div className="input-area">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleSend()}
            placeholder="Ask a question about your data..."
            disabled={loading}
          />
          {loading ? (
            <button className="btn btn-stop stop-btn" onClick={handleStop} title="Stop generating">
              <StopIcon />
              <span>Stop</span>
            </button>
          ) : (
            <div className="input-buttons">
              <button className="btn btn-primary send-btn" onClick={handleSend} disabled={!input.trim()}>
                Send
              </button>
              <button
                className="btn compare-btn"
                onClick={handleCompare}
                disabled={!input.trim()}
                title="A/B compare: run with cache vs without cache"
              >
                <BeakerIcon /> A/B
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

const NODE_ICONS: Record<string, string> = {
  fast_path: '⚡',
  memory: '🧠',
  rewrite: '✏️',
  supervisor: '🎯',
  cache: '💾',
  execute_cached: '▶️',
  populate_params: '🔧',
  genie: '🔮',
  morph: '🔄',
};

function ThinkingPanel({ steps, streaming, defaultOpen }: { steps: ThinkingStep[]; streaming: boolean; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen ?? streaming);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (streaming) setOpen(true);
  }, [streaming, steps.length]);

  useEffect(() => {
    if (open && panelRef.current) {
      const el = panelRef.current;
      el.scrollTop = el.scrollHeight;
    }
  }, [steps.length, open]);

  return (
    <div className={`thinking-panel ${streaming ? 'live' : ''}`}>
      <button className="thinking-toggle" onClick={() => setOpen(o => !o)}>
        <ChevronIcon open={open} />
        <BrainIcon />
        <span className="thinking-toggle-label">
          LLM Thinking
        </span>
        <span className="thinking-badge">{steps.length}</span>
        {streaming && <span className="thinking-live-dot" />}
      </button>
      {open && (
        <div className="thinking-steps" ref={panelRef}>
          {steps.map((s, i) => (
            <div key={i} className={`thinking-step node-${s.node}`}>
              <span className="thinking-icon">{NODE_ICONS[s.node] || '💭'}</span>
              <div className="thinking-body">
                <span className="thinking-label">{s.label}</span>
                <span className="thinking-detail">{s.detail}</span>
              </div>
              <span className="thinking-time">{(s.elapsed_ms / 1000).toFixed(1)}s</span>
            </div>
          ))}
          {streaming && (
            <div className="thinking-step thinking-active">
              <span className="thinking-icon"><Spinner /></span>
              <div className="thinking-body">
                <span className="thinking-label thinking-label-active">Processing...</span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ResponseMeta({ response }: { response: AskResponse }) {
  const subs = response.sub_results;
  const isMultiSource = subs && subs.length > 1;
  const isHit = response.cache_status === 'hit';
  const latencySec = (response.latency_ms / 1000).toFixed(1);
  const genieLatencySec = response.genie_latency_ms != null
    ? (response.genie_latency_ms / 1000).toFixed(1)
    : null;

  if (isMultiSource) {
    const cacheCount = subs.filter(s => s.cache_hit).length;
    const genieCount = subs.length - cacheCount;
    return (
      <div className="response-meta-bar meta-multi">
        <div className="meta-left">
          <span className="meta-status-badge meta-multi-badge">
            <span className="meta-status-icon">📊</span>
            Combined from {subs.length} sources
          </span>
          <span className="meta-source-breakdown">
            {cacheCount > 0 && <span className="meta-source-chip chip-hit">⚡ {cacheCount} cached</span>}
            {genieCount > 0 && <span className="meta-source-chip chip-genie">🔮 {genieCount} Genie</span>}
          </span>
        </div>
        <div className="meta-right">
          {response.memory_context && response.memory_context.length > 0 && (
            <span className="meta-memory-badge" title={response.memory_context.join('; ')}>
              🧠 {response.memory_context.length} memor{response.memory_context.length === 1 ? 'y' : 'ies'}
            </span>
          )}
          <span className="meta-latency">{latencySec}s total</span>
          {response.mlflow_trace_url && (
            <a href={response.mlflow_trace_url} target="_blank" rel="noopener noreferrer" className="meta-trace-link">
              <TraceIcon /> Trace
            </a>
          )}
        </div>
      </div>
    );
  }

  const isUnavailable = response.cache_status === 'unavailable';
  const statusLabel = isHit
    ? 'Cache Hit'
    : isUnavailable
      ? 'Genie (cache unavailable)'
      : 'Genie';
  const statusClass = isHit ? 'meta-hit' : isUnavailable ? 'meta-unavailable' : 'meta-miss';
  const statusIcon = isHit ? '⚡' : isUnavailable ? '⚠️' : '🔮';

  return (
    <div className={`response-meta-bar ${statusClass}`}>
      <div className="meta-left">
        <span className="meta-status-badge">
          <span className="meta-status-icon">{statusIcon}</span>
          {statusLabel}
          {response.similarity_score != null && (
            <span className="meta-score">{(response.similarity_score * 100).toFixed(0)}%</span>
          )}
        </span>
        {response.selected_space_title && (
          <span className="meta-space">{response.selected_space_title}</span>
        )}
      </div>
      <div className="meta-right">
        {response.memory_context && response.memory_context.length > 0 && (
          <span className="meta-memory-badge" title={response.memory_context.join('; ')}>
            🧠 {response.memory_context.length} memor{response.memory_context.length === 1 ? 'y' : 'ies'}
          </span>
        )}
        <span className="meta-latency">
          {latencySec}s
          {isHit && genieLatencySec && (
            <span className="meta-latency-compare"> vs {genieLatencySec}s via Genie</span>
          )}
        </span>
        {response.mlflow_trace_url && (
          <a href={response.mlflow_trace_url} target="_blank" rel="noopener noreferrer" className="meta-trace-link">
            <TraceIcon /> Trace
          </a>
        )}
      </div>
    </div>
  );
}

function ComparisonCard({ comparison, streaming, statusText }: {
  comparison: ComparisonData;
  streaming: boolean;
  statusText: string;
}) {
  const { responseA, responseB, thinkingA, thinkingB, summary, phase } = comparison;
  const isDone = phase === 'done' && summary;

  return (
    <div className="comparison-card">
      <div className="comparison-title">A/B Cache Comparison</div>

      {/* Phase indicator while streaming */}
      {streaming && (
        <div className="comparison-phase">
          <span className={`phase-dot ${responseA ? 'done' : 'active'}`} />
          <span className="phase-label">Run A (with cache)</span>
          <span className={`phase-dot ${responseB ? 'done' : 'active'}`} />
          <span className="phase-label">Run B (no cache)</span>
          <span className="phase-status">Running in parallel...</span>
        </div>
      )}

      <div className="comparison-grid">
        {/* Side A: With Cache */}
        <div className="comparison-side side-a">
          <div className="side-header">
            <span className="side-icon">⚡</span> With Cache
          </div>
          {thinkingA && thinkingA.length > 0 && (
            <ThinkingPanel steps={thinkingA} streaming={phase === 'running_a'} />
          )}
          {responseA ? (
            <div className="side-result">
              <div className="side-status">
                <span className={`side-badge ${responseA.cache_status === 'hit' ? 'badge-hit' : 'badge-miss'}`}>
                  {responseA.cache_status === 'hit' ? 'Cache Hit' : 'Genie'}
                  {responseA.similarity_score != null && ` (${(responseA.similarity_score * 100).toFixed(0)}%)`}
                </span>
                <span className="side-latency">{(responseA.latency_ms / 1000).toFixed(1)}s</span>
              </div>
              {responseA.description && (
                <div className="side-description markdown-content">
                  <ReactMarkdown>{responseA.description}</ReactMarkdown>
                </div>
              )}
              {responseA.columns && responseA.data && responseA.data.length > 0 && (
                <DataTable columns={responseA.columns} data={responseA.data} />
              )}
              {responseA.sql && <SqlCollapsible sql={responseA.sql} label="SQL" />}
            </div>
          ) : (
            phase !== 'pending' && <div className="side-loading">Running...</div>
          )}
        </div>

        {/* Side B: Without Cache */}
        <div className="comparison-side side-b">
          <div className="side-header">
            <span className="side-icon">🔮</span> Without Cache (Genie)
          </div>
          {thinkingB && thinkingB.length > 0 && (
            <ThinkingPanel steps={thinkingB} streaming={phase === 'running_b'} defaultOpen={true} />
          )}
          {responseB ? (
            <div className="side-result">
              <div className="side-status">
                <span className="side-badge badge-miss">Genie</span>
                <span className="side-latency">{(responseB.latency_ms / 1000).toFixed(1)}s</span>
              </div>
              {responseB.description && (
                <div className="side-description markdown-content">
                  <ReactMarkdown>{responseB.description}</ReactMarkdown>
                </div>
              )}
              {responseB.columns && responseB.data && responseB.data.length > 0 && (
                <DataTable columns={responseB.columns} data={responseB.data} />
              )}
              {responseB.sql && <SqlCollapsible sql={responseB.sql} label="SQL" />}
            </div>
          ) : (
            phase === 'running_b' && <div className="side-loading">Running...</div>
          )}
        </div>
      </div>

      {/* Savings summary */}
      {isDone && summary && (
        <div className="comparison-summary">
          <div className="summary-stat summary-saved">
            <span className="summary-label">Time Saved</span>
            <span className="summary-value">
              {summary.saved_ms > 0
                ? `${(summary.saved_ms / 1000).toFixed(1)}s faster (${summary.saved_pct.toFixed(0)}%)`
                : 'No savings (cache miss)'}
            </span>
          </div>
          <div className="summary-stat summary-latencies">
            <span className="summary-label">Latency</span>
            <span className="summary-value">
              {(summary.latency_a_ms / 1000).toFixed(1)}s vs {(summary.latency_b_ms / 1000).toFixed(1)}s
            </span>
          </div>
          <div className="summary-stat summary-match">
            <span className="summary-label">Results</span>
            <span className="summary-value">
              {summary.results_match ? '✓ Match' : '~ Differ'}
            </span>
          </div>
          {summary.saved_ms > 0 && (
            <div className="summary-bar-container">
              <div className="summary-bar">
                <div className="summary-bar-a" style={{ width: `${Math.min(100, (summary.latency_a_ms / summary.latency_b_ms) * 100)}%` }}>
                  A: {(summary.latency_a_ms / 1000).toFixed(1)}s
                </div>
              </div>
              <div className="summary-bar">
                <div className="summary-bar-b" style={{ width: '100%' }}>
                  B: {(summary.latency_b_ms / 1000).toFixed(1)}s
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatCell(value: any): string {
  if (value == null) return '';
  if (typeof value === 'number') {
    if (Number.isInteger(value) && Math.abs(value) >= 1000) {
      return value.toLocaleString();
    }
    if (!Number.isInteger(value)) {
      return value.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 2 });
    }
  }
  return String(value);
}

function DataTable({ columns, data, maxRows = 10 }: {
  columns: string[];
  data: any[][];
  maxRows?: number;
}) {
  const [copied, setCopied] = useState(false);
  const visibleData = data.slice(0, maxRows);
  const hasMore = data.length > maxRows;

  const handleCopyCSV = () => {
    const header = columns.join('\t');
    const rows = data.map(row => row.map((c: any) => c?.toString() ?? '').join('\t'));
    navigator.clipboard.writeText([header, ...rows].join('\n'));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="data-table-container">
      <div className="data-table-header">
        <span className="data-table-count">{data.length} row{data.length !== 1 ? 's' : ''}</span>
        <button className="data-table-copy" onClick={handleCopyCSV} title="Copy as TSV">
          {copied ? '✓ Copied' : '📋 Copy'}
        </button>
      </div>
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>{columns.map(col => <th key={col}>{col}</th>)}</tr>
          </thead>
          <tbody>
            {visibleData.map((row, ri) => (
              <tr key={ri} className={ri % 2 === 1 ? 'alt-row' : ''}>
                {row.map((cell: any, ci: number) => (
                  <td key={ci} title={cell != null && String(cell).length > 40 ? String(cell) : undefined}>
                    {formatCell(cell)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {hasMore && (
        <div className="data-table-footer">
          Showing {visibleData.length} of {data.length} rows
        </div>
      )}
    </div>
  );
}

function BrainIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2a7 7 0 0 0-7 7c0 2.38 1.19 4.47 3 5.74V17a2 2 0 0 0 2 2h4a2 2 0 0 0 2-2v-2.26c1.81-1.27 3-3.36 3-5.74a7 7 0 0 0-7-7z" />
      <path d="M9 21h6" />
    </svg>
  );
}

function SqlCollapsible({ sql, label }: { sql: string; label?: string }) {
  const [open, setOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const preview = sql.replace(/\s+/g, ' ').trim().slice(0, 80);

  const handleCopy = (e: React.MouseEvent) => {
    e.stopPropagation();
    navigator.clipboard.writeText(sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="sql-collapsible">
      <button className="sql-toggle" onClick={() => setOpen(o => !o)}>
        <ChevronIcon open={open} />
        <span>{label || 'SQL'}</span>
        {!open && <span className="sql-preview">{preview}{sql.length > 80 ? '...' : ''}</span>}
        <button className="sql-copy-btn" onClick={handleCopy} title="Copy SQL">
          {copied ? '✓' : '📋'}
        </button>
      </button>
      {open && <div className="sql-block">{sql}</div>}
    </div>
  );
}

function GenieTimeline({ steps, totalMs }: { steps: GenieStep[]; totalMs?: number }) {
  const [open, setOpen] = useState(false);

  const terminalStatuses = new Set(['COMPLETED', 'FAILED', 'CANCELLED', 'QUERY_RESULT_EXPIRED']);
  const pipelineSteps = steps.filter(s => !terminalStatuses.has(s.status));
  const totalDuration = totalMs ?? (steps.length > 0 ? steps[steps.length - 1].elapsed_s * 1000 : 0);

  const statusIcons: Record<string, string> = {
    SUBMITTED: '📤',
    FILTERING_CONTEXT: '🔍',
    FETCHING_METADATA: '🔍',
    ASKING_AI: '🤖',
    PENDING_WAREHOUSE: '⏳',
    EXECUTING_QUERY: '⚡',
  };

  return (
    <div className="genie-timeline">
      <button className="timeline-toggle" onClick={() => setOpen(o => !o)}>
        <ChevronIcon open={open} />
        <span className="timeline-toggle-label">
          Genie Execution Timeline
        </span>
        <span className="timeline-total">{(totalDuration / 1000).toFixed(2)}s</span>
      </button>
      {open && (
        <div className="timeline-steps">
          {pipelineSteps.map((step, i) => {
            const barWidth = totalDuration > 0 ? Math.max((step.duration_ms / totalDuration) * 100, 2) : 0;
            return (
              <div key={i} className="timeline-step">
                <div className="timeline-step-header">
                  <span className="timeline-icon">{statusIcons[step.status] || '●'}</span>
                  <span className="timeline-label">{step.label.replace('...', '')}</span>
                  <span className="timeline-duration">{formatDuration(step.duration_ms)}</span>
                </div>
                <div className="timeline-bar-track">
                  <div
                    className={`timeline-bar-fill timeline-bar-${step.status.toLowerCase()}`}
                    style={{ width: `${barWidth}%` }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function ChevronIcon({ open }: { open: boolean }) {
  return (
    <svg
      className={`chevron-icon ${open ? 'open' : ''}`}
      width="14" height="14" viewBox="0 0 24 24"
      fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
    >
      <polyline points="9 18 15 12 9 6" />
    </svg>
  );
}

function Collapsible({ label, badge, children, defaultOpen = false }: {
  label: string;
  badge?: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="collapsible-section">
      <button className="collapsible-toggle" onClick={() => setOpen(o => !o)}>
        <ChevronIcon open={open} />
        <span className="collapsible-label">{label}</span>
        {badge && <span className="collapsible-badge">{badge}</span>}
      </button>
      {open && <div className="collapsible-content">{children}</div>}
    </div>
  );
}

function Spinner() {
  return (
    <svg className="spinner-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
      <circle cx="12" cy="12" r="10" strokeDasharray="60" strokeDashoffset="20" strokeLinecap="round" />
    </svg>
  )
}

function BeakerIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4.5 3h15" /><path d="M6 3v16a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V3" />
      <path d="M6 14h12" />
    </svg>
  );
}

function StopIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" stroke="none">
      <rect x="4" y="4" width="16" height="16" rx="2" />
    </svg>
  );
}

function TraceIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}

function GenieIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  );
}

function ThumbsUp() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
}
function ThumbsDown() {
  return <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
}

function ExternalLinkMini() {
  return (
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
      <polyline points="15 3 21 3 21 9" />
      <line x1="10" y1="14" x2="21" y2="3" />
    </svg>
  );
}
