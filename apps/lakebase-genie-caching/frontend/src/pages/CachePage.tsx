import { useState, useEffect } from 'react'
import {
  getCacheEntries, deleteCacheEntry, clearAllCacheEntries, triggerPipeline, uploadFAQ,
  pinCacheEntry, CacheEntry, FAQUploadRequest, GenieSpaceInfo, getActiveSpaces,
} from '../api'

export default function CachePage() {
  const [entries, setEntries] = useState<CacheEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [pipelineStatus, setPipelineStatus] = useState<string | null>(null);

  // FAQ upload form
  const [showFaqForm, setShowFaqForm] = useState(false);
  const [faqQuestion, setFaqQuestion] = useState('');
  const [faqSql, setFaqSql] = useState('');
  const [faqSpaceId, setFaqSpaceId] = useState('');
  const [faqUploading, setFaqUploading] = useState(false);
  const [faqStatus, setFaqStatus] = useState<string | null>(null);
  const [activeSpaces, setActiveSpaces] = useState<GenieSpaceInfo[]>([]);

  // Expanded rows for showing parameters/metadata
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadEntries = async () => {
    setLoading(true);
    try {
      const data = await getCacheEntries();
      setEntries(Array.isArray(data?.entries) ? data.entries : []);
      setTotal(data?.total ?? 0);
    } catch (err) {
      console.error('Failed to load cache entries', err);
    }
    setLoading(false);
  };

  useEffect(() => {
    loadEntries();
    getActiveSpaces().then(spaces => {
      const safe = Array.isArray(spaces) ? spaces : [];
      setActiveSpaces(safe);
      if (safe.length > 0 && !faqSpaceId) setFaqSpaceId(safe[0].space_id);
    }).catch(() => {});
  }, []);

  const handleDelete = async (id: string) => {
    await deleteCacheEntry(id);
    loadEntries();
  };

  const handlePin = async (id: string, currentPinned: boolean) => {
    await pinCacheEntry(id, !currentPinned);
    setEntries(prev => prev.map(e => e.id === id ? { ...e, pinned: !currentPinned } : e));
  };

  const handleClearAll = async () => {
    if (!confirm(`Are you sure you want to delete all ${total} cache entries? This cannot be undone.`)) return;
    setPipelineStatus('Clearing cache...');
    try {
      const result = await clearAllCacheEntries();
      setPipelineStatus(`Cleared ${result.count} cache entries`);
      loadEntries();
    } catch (err) {
      setPipelineStatus('Failed to clear cache');
    }
    setTimeout(() => setPipelineStatus(null), 5000);
  };

  const handleRunPipeline = async () => {
    setPipelineStatus('running...');
    try {
      const result = await triggerPipeline('cache');
      if (result.run_id) {
        setPipelineStatus(`job_triggered:${result.job_url || ''}:${result.run_id}`);
      } else {
        const raw = result.result;
        const c = raw.cache || raw;
        const m = raw.memory;
        const paramInfo = c.parameterized ? `, ${c.parameterized} parameterized` : '';
        const memInfo = m ? ` | Memory: ${m.added ?? 0} added, ${m.updated ?? 0} updated` : '';
        setPipelineStatus(`Done: ${c.added ?? 0} added${paramInfo}, ${c.skipped ?? 0} skipped${memInfo}`);
        loadEntries();
      }
    } catch (err) {
      setPipelineStatus('Failed');
    }
    setTimeout(() => setPipelineStatus(null), 15000);
  };

  const handleFaqSubmit = async () => {
    if (!faqQuestion.trim() || !faqSql.trim() || !faqSpaceId) return;
    setFaqUploading(true);
    setFaqStatus(null);
    try {
      const req: FAQUploadRequest = {
        question: faqQuestion.trim(),
        sql: faqSql.trim(),
        genie_space_id: faqSpaceId,
      };
      await uploadFAQ(req);
      setFaqStatus('FAQ added successfully!');
      setFaqQuestion('');
      setFaqSql('');
      setShowFaqForm(false);
      loadEntries();
    } catch (err) {
      setFaqStatus('Failed to upload FAQ');
    }
    setFaqUploading(false);
    setTimeout(() => setFaqStatus(null), 4000);
  };

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Semantic Cache</h1>
            <p>{total} cached entries using pgvector cosine similarity</p>
            <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, maxWidth: 600 }}>
              The cache pipeline scans traces with positive feedback and promotes their
              query/SQL pairs into the semantic cache. Entries can be raw SQL or parameterized
              templates. You can also upload curated FAQ entries.
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button className="btn" onClick={loadEntries}>Refresh</button>
            <button className="btn" onClick={() => setShowFaqForm(!showFaqForm)}>
              {showFaqForm ? 'Cancel' : 'Upload FAQ'}
            </button>
            <button className="btn btn-primary" onClick={handleRunPipeline}>
              Run Cache Pipeline
            </button>
            {total > 0 && (
              <button className="btn" onClick={handleClearAll}
                style={{ color: 'var(--error)', borderColor: 'var(--error)' }}>
                Clear All
              </button>
            )}
          </div>
        </div>

        {pipelineStatus && (
          <div style={{
            marginTop: 12, padding: '8px 16px', borderRadius: 8,
            background: 'rgba(79,110,247,0.1)', fontSize: 13, color: 'var(--accent)'
          }}>
            {pipelineStatus.startsWith('job_triggered:') ? (
              <span>
                Batch job triggered.{' '}
                {pipelineStatus.split(':')[1] && (
                  <a href={pipelineStatus.split(':').slice(1, -1).join(':')} target="_blank" rel="noopener noreferrer"
                    style={{ color: 'var(--accent)', textDecoration: 'underline' }}>
                    View run in Databricks
                  </a>
                )}
              </span>
            ) : (
              <span>Pipeline: {pipelineStatus}</span>
            )}
          </div>
        )}

        {faqStatus && (
          <div style={{
            marginTop: 12, padding: '8px 16px', borderRadius: 8,
            background: faqStatus.includes('success') ? 'rgba(52,199,89,0.1)' : 'rgba(255,69,58,0.1)',
            fontSize: 13,
            color: faqStatus.includes('success') ? '#34c759' : '#ff453a',
          }}>
            {faqStatus}
          </div>
        )}
      </div>

      {/* FAQ Upload Form */}
      {showFaqForm && (
        <div className="card" style={{ marginBottom: 16 }}>
          <h3 style={{ margin: '0 0 12px 0', fontSize: 15 }}>Upload FAQ Entry</h3>
          <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginBottom: 12 }}>
            Add a curated question → SQL pair scoped to a specific Genie space.
            On cache hit the SQL will be executed against the warehouse.
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <select
              value={faqSpaceId}
              onChange={e => setFaqSpaceId(e.target.value)}
              style={{
                padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
                fontSize: 14, background: 'var(--bg-secondary)', color: 'var(--text-primary)',
              }}
            >
              {activeSpaces.length === 0 && <option value="">No active spaces — select spaces on the Config page</option>}
              {activeSpaces.map(s => (
                <option key={s.space_id} value={s.space_id}>{s.title}</option>
              ))}
            </select>
            <input
              type="text"
              placeholder="Question (e.g. How many clinical trials are there?)"
              value={faqQuestion}
              onChange={e => setFaqQuestion(e.target.value)}
              style={{
                padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
                fontSize: 14, background: 'var(--bg-secondary)',
              }}
            />
            <textarea
              placeholder="SQL (e.g. SELECT COUNT(*) FROM trials)"
              value={faqSql}
              onChange={e => setFaqSql(e.target.value)}
              rows={4}
              style={{
                padding: '8px 12px', borderRadius: 8, border: '1px solid var(--border)',
                fontSize: 13, fontFamily: 'monospace', background: 'var(--bg-secondary)', resize: 'vertical',
              }}
            />
            <button
              className="btn btn-primary"
              onClick={handleFaqSubmit}
              disabled={faqUploading || !faqQuestion.trim() || !faqSql.trim() || !faqSpaceId}
              style={{ alignSelf: 'flex-start' }}
            >
              {faqUploading ? 'Uploading...' : 'Add FAQ'}
            </button>
          </div>
        </div>
      )}

      <div className="card">
        {loading ? (
          <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>Loading...</p>
        ) : entries.length === 0 ? (
          <p style={{ color: 'var(--text-secondary)', textAlign: 'center', padding: 40 }}>
            No cache entries yet. Use the Chat page to ask questions, give thumbs-up, then run the cache pipeline.
            Or upload FAQ entries above.
          </p>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ width: 36 }}></th>
                <th>Type</th>
                <th>Query</th>
                <th>Space</th>
                <th>Hits</th>
                <th>Created</th>
                <th>SQL Preview</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {entries.map(entry => (
                <>
                  <tr key={entry.id} onClick={() => setExpandedId(expandedId === entry.id ? null : entry.id)}
                      style={{ cursor: 'pointer' }}>
                    <td style={{ textAlign: 'center', padding: '0 4px' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); handlePin(entry.id, !!entry.pinned); }}
                        title={entry.pinned ? 'Unpin (allow eviction)' : 'Pin (prevent eviction)'}
                        style={{
                          background: 'none', border: 'none', cursor: 'pointer', padding: 4,
                          fontSize: 16, lineHeight: 1,
                          opacity: entry.pinned ? 1 : 0.3,
                          filter: entry.pinned ? 'none' : 'grayscale(1)',
                        }}
                      >
                        📌
                      </button>
                    </td>
                    <td>
                      <span className={`badge ${entry.record_type === 'faq' ? 'faq' : 'trace'}`}
                        style={{
                          background: entry.record_type === 'faq' ? 'rgba(52,199,89,0.15)' : 'rgba(79,110,247,0.15)',
                          color: entry.record_type === 'faq' ? '#34c759' : 'var(--accent)',
                          fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
                        }}>
                        {(entry.record_type || 'trace').toUpperCase()}
                      </span>
                    </td>
                    <td style={{ maxWidth: 320 }}>
                      <div style={{ fontWeight: 500 }}>{entry.query_text}</div>
                      {entry.parameterized_sql && entry.parameters && Object.keys(entry.parameters).length > 0 && (
                        <div style={{ marginTop: 4 }}>
                          <span style={{ fontSize: 10, color: '#ff9f0a', fontWeight: 600 }}>PARAMETERIZED</span>
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 3 }}>
                            {Object.entries(entry.parameters).map(([k, v]) => (
                              <span key={k} style={{
                                fontSize: 10, padding: '1px 6px', borderRadius: 4,
                                background: 'rgba(255,159,10,0.12)', color: '#ff9f0a',
                                fontFamily: 'monospace',
                              }}>
                                :{k} = {String(v)}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--text-secondary)', maxWidth: 120 }}>
                      {entry.genie_space_id ? entry.genie_space_id.slice(0, 12) + '...' : '—'}
                    </td>
                    <td>
                      <span className="badge hit">{entry.hit_count}</span>
                    </td>
                    <td style={{ fontSize: 12, color: 'var(--text-secondary)' }}>
                      {new Date(entry.created_at).toLocaleString()}
                    </td>
                    <td style={{ maxWidth: 300 }}>
                      <div className="sql-block" style={{ maxHeight: 60, fontSize: 11 }}>
                        {(entry.cached_sql || '').substring(0, 200)}
                      </div>
                    </td>
                    <td>
                      <button className="btn btn-sm" onClick={(e) => { e.stopPropagation(); handleDelete(entry.id); }}
                        style={{ color: 'var(--error)' }}>
                        Delete
                      </button>
                    </td>
                  </tr>
                  {expandedId === entry.id && (
                    <tr key={`${entry.id}-detail`}>
                      <td colSpan={8} style={{ padding: '12px 16px', background: 'var(--bg-secondary)' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, fontSize: 12 }}>
                          {entry.parameterized_sql && (
                            <div>
                              <div style={{ fontWeight: 600, marginBottom: 4, color: '#ff9f0a' }}>
                                Parameterized SQL Template
                              </div>
                              <pre style={{
                                background: 'var(--bg-primary)', padding: 8, borderRadius: 6,
                                fontSize: 11, overflow: 'auto', maxHeight: 120,
                              }}>
                                {entry.parameterized_sql}
                              </pre>
                            </div>
                          )}
                          {entry.parameters && Object.keys(entry.parameters).length > 0 && (
                            <div>
                              <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--accent)' }}>
                                Parameters
                              </div>
                              <pre style={{
                                background: 'var(--bg-primary)', padding: 8, borderRadius: 6,
                                fontSize: 11, overflow: 'auto', maxHeight: 120,
                              }}>
                                {JSON.stringify(entry.parameters, null, 2)}
                              </pre>
                            </div>
                          )}
                          {entry.metadata && Object.keys(entry.metadata).length > 0 && (
                            <div>
                              <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-secondary)' }}>
                                Metadata
                              </div>
                              <pre style={{
                                background: 'var(--bg-primary)', padding: 8, borderRadius: 6,
                                fontSize: 11, overflow: 'auto', maxHeight: 120,
                              }}>
                                {JSON.stringify(entry.metadata, null, 2)}
                              </pre>
                            </div>
                          )}
                          <div>
                            <div style={{ fontWeight: 600, marginBottom: 4, color: 'var(--text-secondary)' }}>
                              Genie Space ID
                            </div>
                            <div style={{
                              background: 'var(--bg-primary)', padding: 8, borderRadius: 6,
                              fontSize: 11, fontFamily: 'monospace',
                            }}>
                              {entry.genie_space_id || '(none)'}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontWeight: 600, marginBottom: 4 }}>Full SQL</div>
                            <pre style={{
                              background: 'var(--bg-primary)', padding: 8, borderRadius: 6,
                              fontSize: 11, overflow: 'auto', maxHeight: 120,
                            }}>
                              {entry.cached_sql || '(no SQL)'}
                            </pre>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
