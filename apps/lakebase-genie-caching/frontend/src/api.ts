const BASE = '/api';

export interface WhoAmI {
  user_id: string;
  display_name?: string;
  email?: string;
}

export interface AppConfig {
  workspace_host: string;
  org_id: string;
  experiment_id: string;
  workspace_folder: string;
  workspace_user: string;
  lakebase_instance: string;
  warehouse_id: string;
  resource_links: {
    mlflow_traces: string | null;
    lakebase: string | null;
    trace_archive_table: string | null;
    trace_archive_job: string | null;
    batch_pipelines_job: string | null;
  };
}

export interface LandingData {
  active_spaces: GenieSpaceInfo[];
  sample_questions: SampleQuestion[];
  cache_entries: CacheEntry[];
}

let _cachedConfig: AppConfig | null = null;
let _cachedUser: WhoAmI | null = null;

export async function getConfig(): Promise<AppConfig | null> {
  if (_cachedConfig) return _cachedConfig;
  try {
    const res = await fetch(`${BASE}/config`);
    if (!res.ok) return null;
    _cachedConfig = await res.json();
    return _cachedConfig;
  } catch {
    return null;
  }
}

export async function whoami(): Promise<WhoAmI> {
  if (_cachedUser) return _cachedUser;
  try {
    const res = await fetch(`${BASE}/whoami`);
    if (!res.ok) throw new Error('whoami failed');
    _cachedUser = await res.json();
    return _cachedUser!;
  } catch {
    return { user_id: 'unknown' };
  }
}

export async function getCurrentUserId(): Promise<string> {
  const me = await whoami();
  return me.user_id;
}

export interface AskResponse {
  question: string;
  rewritten_question?: string;
  intent?: string;
  sql?: string;
  description?: string;
  columns?: string[];
  data?: any[][];
  row_count?: number;
  cache_status: 'hit' | 'miss' | 'rejected' | 'unavailable';
  similarity_score?: number;
  latency_ms: number;
  genie_latency_ms?: number;
  trace_id: string;
  session_id: string;
  session_title?: string;
  memory_context?: string[];
  genie_steps?: GenieStep[];
  follow_up_questions?: string[];
  mlflow_trace_url?: string;
  selected_space_id?: string;
  selected_space_title?: string;
  sub_results?: SubResult[];
  supervisor_plan?: { agent: string; task: string }[];
}

export interface SubResult {
  space_id: string;
  space_title: string;
  sub_question: string;
  sql?: string;
  columns?: string[];
  data?: any[][];
  row_count?: number;
  description?: string;
  cache_hit?: boolean;
}

export interface GenieStep {
  status: string;
  label: string;
  elapsed_s: number;
  duration_ms: number;
}

export interface CacheEntry {
  id: string;
  query_text: string;
  query_normalized: string;
  cached_sql: string;
  genie_space_id: string;
  hit_count: number;
  created_at: string;
  updated_at: string;
  record_type?: 'faq' | 'trace';
  result?: string;
  parameterized_sql?: string;
  parameters?: Record<string, any>;
  metadata?: Record<string, any>;
  pinned?: boolean;
  ttl_expiry?: string;
}

export interface FAQUploadRequest {
  question: string;
  sql: string;
  genie_space_id: string;
  metadata?: Record<string, any>;
}

export interface Metrics {
  total_queries: number;
  cache_hits: number;
  cache_misses: number;
  cache_rejections: number;
  hit_rate: number;
  avg_latency_hit_ms: number;
  avg_latency_miss_ms: number;
  latency_savings_ms: number;
  cache_size: number;
}

export interface STMSession {
  session_id: string;
  user_id: string;
  title?: string;
  created_at: string;
  updated_at: string;
}

export interface STMMessage {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  created_at: string;
}

export type MemoryType = 'preference' | 'correction' | 'avoidance' | 'definition' | 'identity';

export interface MemoryEntry {
  id: string;
  user_id: string;
  content: string;
  memory_type: MemoryType;
  score: number;
  recurrence_count: number;
  last_seen_at: string;
  created_at: string;
  archived_at?: string | null;
}

export interface StreamEvent {
  event: string;
  data: any;
}

export async function askStream(
  question: string,
  onEvent: (event: StreamEvent) => void,
  sessionId?: string,
  userId?: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/ask/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId, user_id: userId }),
    signal,
  });
  if (!res.ok) throw new Error(await res.text());
  if (!res.body) throw new Error('No response body');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const processLines = (lines: string[], currentEvent: string): string => {
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ') && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ event: currentEvent, data });
        } catch (e) {
          console.warn(`SSE parse error for event '${currentEvent}':`, e, 'raw:', line.slice(6, 200));
        }
        currentEvent = '';
      }
    }
    return currentEvent;
  };

  try {
    let currentEvent = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      currentEvent = processLines(lines, currentEvent);
    }

    // Flush any remaining data in the buffer after stream ends
    if (buffer.trim()) {
      const remaining = buffer.split('\n');
      processLines(remaining, currentEvent);
    }
  } finally {
    try { reader.cancel(); } catch { /* already closed */ }
  }
}

export interface ComparisonResult {
  latency_a_ms: number;
  latency_b_ms: number;
  saved_ms: number;
  saved_pct: number;
  cache_status_a: string;
  results_match: boolean;
  question: string;
}

export async function compareStream(
  question: string,
  onEvent: (event: StreamEvent) => void,
  userId?: string,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${BASE}/compare/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, user_id: userId }),
    signal,
  });
  if (!res.ok) throw new Error(await res.text());
  if (!res.body) throw new Error('No response body');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  const processLines = (lines: string[], currentEvent: string): string => {
    for (const line of lines) {
      if (line.startsWith('event: ')) {
        currentEvent = line.slice(7).trim();
      } else if (line.startsWith('data: ') && currentEvent) {
        try {
          const data = JSON.parse(line.slice(6));
          onEvent({ event: currentEvent, data });
        } catch (e) {
          console.warn(`SSE parse error for event '${currentEvent}':`, e);
        }
        currentEvent = '';
      }
    }
    return currentEvent;
  };

  try {
    let currentEvent = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() || '';
      currentEvent = processLines(lines, currentEvent);
    }
    if (buffer.trim()) {
      const remaining = buffer.split('\n');
      processLines(remaining, currentEvent);
    }
  } finally {
    try { reader.cancel(); } catch { /* already closed */ }
  }
}

export async function submitFeedback(traceId: string, rating: number, userId?: string) {
  const res = await fetch(`${BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ trace_id: traceId, rating, user_id: userId }),
  });
  return res.json();
}

export async function getCacheEntries(limit = 50, offset = 0): Promise<{ entries: CacheEntry[]; total: number }> {
  const res = await fetch(`${BASE}/cache/entries?limit=${limit}&offset=${offset}`);
  return res.json();
}

export async function deleteCacheEntry(id: string) {
  return fetch(`${BASE}/cache/entries/${id}`, { method: 'DELETE' }).then(r => r.json());
}

export async function pinCacheEntry(id: string, pinned: boolean): Promise<{ id: string; pinned: boolean }> {
  const res = await fetch(`${BASE}/cache/entries/${id}/pin`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ pinned }),
  });
  return res.json();
}

export async function clearAllCacheEntries(): Promise<{ cleared: boolean; count: number }> {
  const res = await fetch(`${BASE}/cache/entries`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Clear cache failed: ${res.status}`);
  return res.json();
}

export async function getMetrics(): Promise<Metrics> {
  const res = await fetch(`${BASE}/memory/metrics`);
  return res.json();
}

export async function getSessions(userId: string, limit = 20): Promise<{ sessions: STMSession[] }> {
  const res = await fetch(`${BASE}/memory/sessions/${userId}?limit=${limit}`);
  return res.json();
}

export async function getSessionHistory(userId: string, sessionId: string): Promise<{ session: STMSession | null; messages: STMMessage[] }> {
  const res = await fetch(`${BASE}/memory/sessions/${userId}/${sessionId}`);
  return res.json();
}

export async function renameSession(sessionId: string, title: string): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE}/memory/sessions/${sessionId}/rename`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`Rename failed: ${res.status}`);
  return res.json();
}

export async function getMemoryEntries(userId: string): Promise<{ entries: MemoryEntry[] }> {
  const res = await fetch(`${BASE}/memory/entries/${userId}`);
  return res.json();
}

export async function deleteMemoryEntry(userId: string, entryId: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE}/memory/entries/${userId}/${entryId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Delete memory entry failed: ${res.status}`);
  return res.json();
}

export async function clearAllMemoryEntries(userId: string): Promise<{ cleared: boolean; count: number }> {
  const res = await fetch(`${BASE}/memory/entries/${userId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Clear memories failed: ${res.status}`);
  return res.json();
}

export async function restoreMemoryEntry(userId: string, entryId: string): Promise<{ restored: boolean }> {
  const res = await fetch(`${BASE}/memory/entries/${userId}/${entryId}/restore`, { method: 'POST' });
  if (!res.ok) throw new Error(`Restore memory entry failed: ${res.status}`);
  return res.json();
}

export async function deleteSession(userId: string, sessionId: string): Promise<{ deleted: boolean }> {
  const res = await fetch(`${BASE}/memory/sessions/${userId}/${sessionId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Delete session failed: ${res.status}`);
  return res.json();
}

export async function clearAllSessions(userId: string): Promise<{ cleared: boolean; count: number }> {
  const res = await fetch(`${BASE}/memory/sessions/${userId}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Clear sessions failed: ${res.status}`);
  return res.json();
}

export async function triggerPipeline(name: string, userId?: string): Promise<any> {
  const url = userId ? `${BASE}/pipelines/${name}/${userId}` : `${BASE}/pipelines/${name}`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Pipeline ${name} failed (${res.status}): ${text}`);
  }
  return res.json();
}

export async function uploadFAQ(faq: FAQUploadRequest): Promise<{ entry: CacheEntry }> {
  const res = await fetch(`${BASE}/cache/faq`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(faq),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// ---------------------------------------------------------------------------
// Genie Spaces
// ---------------------------------------------------------------------------

export interface GenieSpaceInfo {
  space_id: string;
  title: string;
  description?: string;
  warehouse_id?: string;
  genie_room_url?: string;
  active?: boolean;
}

// ---------------------------------------------------------------------------
// Tuning / Config
// ---------------------------------------------------------------------------

export interface TuningConfig {
  cache: {
    similarity_threshold: number;
    answer_morph_threshold: number;
    top_k: number;
    ttl_hours: number;
    max_age_days: number;
    stale_days: number;
  };
  memory: {
    similarity_threshold: number;
    score_threshold: number;
    top_k: number;
    max_age_days: number;
    decay_rate: number;
    blocklist_threshold: number;
  };
  llm: {
    classifier_endpoint: string;
    assistant_endpoint: string;
  };
}

export async function getTuning(): Promise<TuningConfig> {
  const res = await fetch(`${BASE}/tuning`);
  if (!res.ok) throw new Error('Failed to load tuning config');
  return res.json();
}

export async function updateTuning(partial: Partial<TuningConfig>): Promise<{ updated: string[] }> {
  const res = await fetch(`${BASE}/tuning`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(partial),
  });
  if (!res.ok) throw new Error('Failed to update tuning config');
  return res.json();
}

export async function getActiveSpaces(): Promise<GenieSpaceInfo[]> {
  const res = await fetch(`${BASE}/genie/spaces/active`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function getAllSpaces(): Promise<GenieSpaceInfo[]> {
  return getActiveSpaces();
}

export interface SampleQuestion {
  question: string;
  space_id?: string;
  space_title: string;
  badge?: string | null;
}

export async function getSampleQuestions(): Promise<SampleQuestion[]> {
  const res = await fetch(`${BASE}/sample-questions`);
  if (!res.ok) return [];
  const data = await res.json();
  return Array.isArray(data) ? data : [];
}

export async function getLandingData(): Promise<LandingData> {
  const res = await fetch(`${BASE}/landing-data`);
  if (!res.ok) throw new Error(`landing data failed: ${res.status}`);
  const data = await res.json();
  return {
    active_spaces: Array.isArray(data.active_spaces) ? data.active_spaces : [],
    sample_questions: Array.isArray(data.sample_questions) ? data.sample_questions : [],
    cache_entries: Array.isArray(data.cache_entries) ? data.cache_entries : [],
  };
}
