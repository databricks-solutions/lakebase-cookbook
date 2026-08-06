import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import ReactMarkdown from 'react-markdown'
import {
  getMemoryEntries, getSessions, getSessionHistory, triggerPipeline,
  getCurrentUserId, renameSession, deleteMemoryEntry, clearAllMemoryEntries,
  deleteSession, clearAllSessions,
  MemoryEntry, MemoryType, STMSession, STMMessage,
} from '../api'

const CHAT_STORAGE_MESSAGES = 'genie-chat-messages';
const CHAT_STORAGE_SESSION = 'genie-chat-session';
const CHAT_STORAGE_TITLE = 'genie-chat-title';

export default function MemoryPage() {
  const navigate = useNavigate();
  const [userId, setUserId] = useState('unknown');

  useEffect(() => {
    getCurrentUserId().then(setUserId);
  }, []);

  const [memory, setMemory] = useState<MemoryEntry[]>([]);
  const [sessions, setSessions] = useState<STMSession[]>([]);
  const [selectedSession, setSelectedSession] = useState<string | null>(null);
  const [sessionMessages, setSessionMessages] = useState<STMMessage[]>([]);
  const [tab, setTab] = useState<'stm' | 'memory'>('stm');
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);

  // Rename state
  const [editingSessionId, setEditingSessionId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');

  const loadData = async () => {
    if (userId === 'unknown') return;
    try {
      const [memoryData, sessionData] = await Promise.all([
        getMemoryEntries(userId),
        getSessions(userId),
      ]);
      setMemory(Array.isArray(memoryData?.entries) ? memoryData.entries : []);
      setSessions(Array.isArray(sessionData?.sessions) ? sessionData.sessions : []);
    } catch (err) {
      console.error('Failed to load memory data', err);
    }
  };

  useEffect(() => { loadData(); }, [userId]);

  const handleSelectSession = async (sessionId: string) => {
    setSelectedSession(sessionId);
    try {
      const data = await getSessionHistory(userId, sessionId);
      setSessionMessages(Array.isArray(data?.messages) ? data.messages : []);
    } catch (err) {
      console.error('Failed to load session history', err);
      setSessionMessages([]);
    }
  };

  const handleStartRename = (s: STMSession, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingSessionId(s.session_id);
    setEditTitle(s.title || '');
  };

  const handleSaveRename = async () => {
    if (!editingSessionId || !editTitle.trim()) return;
    try {
      await renameSession(editingSessionId, editTitle.trim());
      setSessions(prev =>
        prev.map(s => s.session_id === editingSessionId ? { ...s, title: editTitle.trim() } : s)
      );
    } catch (err) {
      console.error('Failed to rename session', err);
    }
    setEditingSessionId(null);
    setEditTitle('');
  };

  const handleCancelRename = () => {
    setEditingSessionId(null);
    setEditTitle('');
  };

  const handleResumeChat = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const data = await getSessionHistory(userId, sessionId);
      // Convert backend messages to ChatPage message format
      const chatMessages = data.messages.map(msg => ({
        role: msg.role as 'user' | 'assistant',
        content: msg.content,
      }));
      // Find the session title
      const session = sessions.find(s => s.session_id === sessionId);
      // Write to ChatPage's sessionStorage keys so it picks them up on mount
      sessionStorage.setItem(CHAT_STORAGE_SESSION, sessionId);
      sessionStorage.setItem(CHAT_STORAGE_MESSAGES, JSON.stringify(chatMessages));
      if (session?.title) {
        sessionStorage.setItem(CHAT_STORAGE_TITLE, session.title);
      } else {
        sessionStorage.removeItem(CHAT_STORAGE_TITLE);
      }
      navigate('/');
    } catch (err) {
      console.error('Failed to resume session', err);
    }
  };

  const handleRunPipeline = async () => {
    setPipelineStatus('Extracting memories from your recent traces...');
    try {
      const result = await triggerPipeline('memory', userId);
      if (result.run_id) {
        setPipelineStatus(`job_triggered:${result.job_url || ''}:${result.run_id}`);
      } else {
        const r = result.result;
        const parts: string[] = [];
        if (r.traces_found !== undefined) parts.push(`${r.traces_found} traces found`);
        if (r.traces_extracted) parts.push(`${r.traces_extracted} processed`);
        if (r.added) parts.push(`${r.added} new memories`);
        if (r.updated) parts.push(`${r.updated} reinforced`);
        if (r.decayed) parts.push(`${r.decayed} decayed`);
        if (r.evicted) parts.push(`${r.evicted} evicted`);
        setPipelineStatus(
          parts.length > 0 ? `Done: ${parts.join(', ')}` : 'Done: no new memories to extract'
        );
        loadData();
      }
    } catch (err: any) {
      setPipelineStatus(`Failed: ${err.message || 'Unknown error'}`);
    }
    setTimeout(() => setPipelineStatus(null), 15000);
  };

  const handleDeleteMemory = async (entryId: string) => {
    try {
      await deleteMemoryEntry(userId, entryId);
      setMemory(prev => prev.filter(e => e.id !== entryId));
    } catch (err) {
      console.error('Failed to delete memory entry', err);
    }
  };

  const handleClearAllMemories = async () => {
    if (!confirm(`Delete all ${memory.length} memory entries? This cannot be undone.`)) return;
    try {
      await clearAllMemoryEntries(userId);
      setMemory([]);
    } catch (err) {
      console.error('Failed to clear memories', err);
    }
  };

  const handleDeleteSession = async (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation();
    if (!confirm('Delete this session and all its messages?')) return;
    try {
      await deleteSession(userId, sessionId);
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
      if (selectedSession === sessionId) {
        setSelectedSession(null);
        setSessionMessages([]);
      }
    } catch (err) {
      console.error('Failed to delete session', err);
    }
  };

  const handleClearAllSessions = async () => {
    if (!confirm(`Delete all ${sessions.length} sessions and their messages? This cannot be undone.`)) return;
    try {
      await clearAllSessions(userId);
      setSessions([]);
      setSelectedSession(null);
      setSessionMessages([]);
    } catch (err) {
      console.error('Failed to clear sessions', err);
    }
  };

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    return d.toLocaleString();
  };

  const timeAgo = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  };

  return (
    <div>
      <div className="page-header">
        <h1>Agentic Memory</h1>
        <p>Short-term memory and user memory for <strong>{userId}</strong></p>
        <div style={{ display: 'flex', gap: 16, marginTop: 8 }}>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 300, margin: 0 }}>
            <strong>STM:</strong> Conversation sessions and message history stored in Lakebase.
            Used for multi-turn query rewriting.
          </p>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', maxWidth: 300, margin: 0 }}>
            <strong>User Memory:</strong> Extracted from MLflow traces by the unified pipeline.
            Types: preference, correction, avoidance, definition.
            Injected into LLM prompts to personalize responses.
          </p>
        </div>
      </div>

      {pipelineStatus && (
        <div style={{
          marginBottom: 16, padding: '8px 16px', borderRadius: 8,
          background: 'rgba(79,110,247,0.1)', fontSize: 13, color: 'var(--accent)'
        }}>
          {pipelineStatus.startsWith('job_triggered:') ? (
            <span>
              Batch job triggered (includes trace archive + cache + memory).{' '}
              {pipelineStatus.split(':')[1] && (
                <a href={pipelineStatus.split(':').slice(1, -1).join(':')} target="_blank" rel="noopener noreferrer"
                  style={{ color: 'var(--accent)', textDecoration: 'underline' }}>
                  View run in Databricks
                </a>
              )}
            </span>
          ) : (
            <span>{pipelineStatus}</span>
          )}
        </div>
      )}

      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        <button
          className={`btn ${tab === 'stm' ? 'btn-primary' : ''}`}
          onClick={() => setTab('stm')}
        >
          Short-Term Memory ({sessions.length})
        </button>
        <button
          className={`btn ${tab === 'memory' ? 'btn-primary' : ''}`}
          onClick={() => setTab('memory')}
        >
          User Memory ({memory.length})
        </button>
        <div style={{ flex: 1 }} />
        {tab === 'stm' && sessions.length > 0 && (
          <button className="btn" onClick={handleClearAllSessions}
            style={{ color: 'var(--error)', borderColor: 'var(--error)' }}>
            Clear All Sessions
          </button>
        )}
        {tab === 'memory' && memory.length > 0 && (
          <button className="btn" onClick={handleClearAllMemories}
            style={{ color: 'var(--error)', borderColor: 'var(--error)' }}>
            Clear All Memories
          </button>
        )}
        <button className="btn" onClick={handleRunPipeline}>
          Run Memory Pipeline
        </button>
        <button className="btn" onClick={loadData}>Refresh</button>
      </div>

      {/* ========= STM Tab ========= */}
      {tab === 'stm' && (
        <div style={{ display: 'flex', gap: 16 }}>
          {/* Session list */}
          <div className="card" style={{ width: 320, flexShrink: 0, maxHeight: 600, overflowY: 'auto' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: 14 }}>Sessions</h3>
            {sessions.length === 0 ? (
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, textAlign: 'center', padding: 20 }}>
                No sessions yet. Start a conversation in the Chat page.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                {sessions.map(s => (
                  <div
                    key={s.session_id}
                    onClick={() => handleSelectSession(s.session_id)}
                    style={{
                      padding: '10px 12px',
                      borderRadius: 8,
                      cursor: 'pointer',
                      background: selectedSession === s.session_id ? 'rgba(79,110,247,0.12)' : 'transparent',
                      border: selectedSession === s.session_id ? '1px solid var(--accent)' : '1px solid transparent',
                      transition: 'all 0.15s',
                    }}
                  >
                    {editingSessionId === s.session_id ? (
                      <div style={{ display: 'flex', gap: 4, alignItems: 'center' }} onClick={e => e.stopPropagation()}>
                        <input
                          type="text"
                          value={editTitle}
                          onChange={e => setEditTitle(e.target.value)}
                          onKeyDown={e => {
                            if (e.key === 'Enter') handleSaveRename();
                            if (e.key === 'Escape') handleCancelRename();
                          }}
                          autoFocus
                          style={{
                            flex: 1, fontSize: 13, padding: '4px 8px', borderRadius: 4,
                            border: '1px solid var(--accent)', background: 'var(--bg-primary)',
                            color: 'var(--text-primary)', outline: 'none',
                          }}
                        />
                        <button onClick={handleSaveRename} style={{
                          fontSize: 11, padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
                          background: 'var(--accent)', color: 'white', border: 'none',
                        }}>Save</button>
                        <button onClick={handleCancelRename} style={{
                          fontSize: 11, padding: '4px 8px', borderRadius: 4, cursor: 'pointer',
                          background: 'var(--bg-secondary)', color: 'var(--text-secondary)', border: '1px solid var(--border)',
                        }}>Cancel</button>
                      </div>
                    ) : (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 4, marginBottom: 2 }}>
                        <span style={{ fontSize: 13, fontWeight: 500, color: 'var(--text-primary)', flex: 1 }}>
                          {s.title || 'Untitled Session'}
                        </span>
                        <button
                          onClick={(e) => handleStartRename(s, e)}
                          title="Rename"
                          style={{
                            background: 'none', border: 'none', cursor: 'pointer', padding: 2,
                            color: 'var(--text-muted)', fontSize: 12, lineHeight: 1, flexShrink: 0,
                            opacity: 0.5, transition: 'opacity 0.15s',
                          }}
                          onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                          onMouseLeave={e => (e.currentTarget.style.opacity = '0.5')}
                        >
                          <PencilIcon />
                        </button>
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 2 }}>
                      <span style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--text-muted)' }}>
                        {s.session_id.substring(0, 8)}...
                      </span>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                        <button
                          onClick={(e) => handleResumeChat(s.session_id, e)}
                          title="Resume this conversation"
                          style={{
                            fontSize: 11, padding: '2px 8px', borderRadius: 4, cursor: 'pointer',
                            background: 'none', color: 'var(--accent)', border: '1px solid var(--accent)',
                            transition: 'all 0.15s', lineHeight: 1.4,
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = 'rgba(79,110,247,0.1)'; }}
                          onMouseLeave={e => { e.currentTarget.style.background = 'none'; }}
                        >
                          Resume
                        </button>
                        <button
                          onClick={(e) => handleDeleteSession(s.session_id, e)}
                          title="Delete session"
                          style={{
                            fontSize: 11, padding: '2px 6px', borderRadius: 4, cursor: 'pointer',
                            background: 'none', color: 'var(--error)', border: '1px solid transparent',
                            transition: 'all 0.15s', lineHeight: 1.4, opacity: 0.5,
                          }}
                          onMouseEnter={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.borderColor = 'var(--error)'; }}
                          onMouseLeave={e => { e.currentTarget.style.opacity = '0.5'; e.currentTarget.style.borderColor = 'transparent'; }}
                        >
                          <TrashIcon />
                        </button>
                        <span style={{ fontSize: 11, color: 'var(--text-secondary)' }}>
                          {timeAgo(s.updated_at)}
                        </span>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Message history */}
          <div className="card" style={{ flex: 1, maxHeight: 600, overflowY: 'auto' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: 14 }}>
              {selectedSession ? `Messages (${sessionMessages.length})` : 'Select a session'}
            </h3>
            {!selectedSession ? (
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, textAlign: 'center', padding: 40 }}>
                Click a session on the left to view its conversation history.
              </p>
            ) : sessionMessages.length === 0 ? (
              <p style={{ color: 'var(--text-secondary)', fontSize: 13, textAlign: 'center', padding: 40 }}>
                No messages in this session.
              </p>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {sessionMessages.map(msg => (
                  <div
                    key={msg.id}
                    style={{
                      padding: '10px 14px',
                      borderRadius: 10,
                      background: msg.role === 'user' ? 'rgba(79,110,247,0.08)' : 'var(--bg-secondary)',
                      borderLeft: msg.role === 'user' ? '3px solid var(--accent)' : '3px solid var(--border)',
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                      <span style={{
                        fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
                        color: msg.role === 'user' ? 'var(--accent)' : 'var(--text-muted)',
                      }}>
                        {msg.role}
                      </span>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                        {formatTime(msg.created_at)}
                      </span>
                    </div>
                    <div style={{
                      fontSize: 13,
                      lineHeight: 1.5,
                      wordBreak: 'break-word',
                      maxHeight: 200,
                      overflow: 'auto',
                    }}>
                      <ReactMarkdown>{msg.content}</ReactMarkdown>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* ========= User Memory Tab ========= */}
      {tab === 'memory' && (
        <div className="card">
          {memory.length === 0 ? (
            <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>
              No user memories yet. Have some conversations and run the memory pipeline.
            </p>
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Type</th>
                  <th>Memory</th>
                  <th>Score</th>
                  <th>Recurrences</th>
                  <th>Last Seen</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {memory.map(entry => (
                  <tr key={entry.id}>
                    <td><MemoryTypeBadge type={entry.memory_type} /></td>
                    <td>{entry.content}</td>
                    <td>
                      <div style={{
                        display: 'flex', alignItems: 'center', gap: 8
                      }}>
                        <div style={{
                          width: 60, height: 6, borderRadius: 3,
                          background: 'var(--border)', overflow: 'hidden'
                        }}>
                          <div style={{
                            width: `${Math.min(entry.score / 5 * 100, 100)}%`,
                            height: '100%', borderRadius: 3,
                            background: entry.score >= 3 ? 'var(--success)' :
                              entry.score >= 1.5 ? 'var(--warning)' : 'var(--text-muted)'
                          }} />
                        </div>
                        <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                          {entry.score.toFixed(1)}
                        </span>
                      </div>
                    </td>
                    <td>{entry.recurrence_count}</td>
                    <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      {new Date(entry.last_seen_at).toLocaleString()}
                    </td>
                    <td>
                      <button
                        className="btn btn-sm"
                        onClick={() => handleDeleteMemory(entry.id)}
                        style={{ color: 'var(--error)', padding: '2px 8px', fontSize: 11 }}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  )
}

const MEMORY_TYPE_STYLES: Record<MemoryType, { bg: string; color: string; label: string }> = {
  identity: { bg: 'rgba(156,39,176,0.12)', color: '#9c27b0', label: 'Identity' },
  preference: { bg: 'rgba(79,110,247,0.12)', color: 'var(--accent)', label: 'Preference' },
  correction: { bg: 'rgba(245,166,35,0.12)', color: '#f5a623', label: 'Correction' },
  avoidance: { bg: 'rgba(235,87,87,0.12)', color: 'var(--error)', label: 'Avoidance' },
  definition: { bg: 'rgba(39,174,96,0.12)', color: 'var(--success)', label: 'Definition' },
};

function MemoryTypeBadge({ type }: { type: MemoryType }) {
  const style = MEMORY_TYPE_STYLES[type] || MEMORY_TYPE_STYLES.preference;
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 600,
      background: style.bg,
      color: style.color,
      whiteSpace: 'nowrap',
    }}>
      {style.label}
    </span>
  );
}

function PencilIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17 3a2.828 2.828 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5L17 3z" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  );
}
