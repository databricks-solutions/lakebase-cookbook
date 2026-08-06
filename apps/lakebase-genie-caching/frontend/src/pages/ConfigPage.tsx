import { useState, useEffect, useCallback } from 'react';
import { getTuning, updateTuning, TuningConfig, GenieSpaceInfo, getActiveSpaces } from '../api';

interface FieldDef {
  key: string;
  label: string;
  description: string;
  min?: number;
  max?: number;
  step?: number;
  type: 'slider' | 'number' | 'readonly';
}

const CACHE_FIELDS: FieldDef[] = [
  { key: 'similarity_threshold', label: 'Direct Hit Threshold (Tier 1)', description: 'Minimum similarity for a direct cache hit — re-executes cached SQL with validation', min: 0.5, max: 1.0, step: 0.01, type: 'slider' },
  { key: 'answer_morph_threshold', label: 'SQL Adaptation Threshold (Tier 2)', description: 'Minimum similarity for SQL adaptation — re-parameterizes and re-executes cached SQL', min: 0.5, max: 1.0, step: 0.01, type: 'slider' },
  { key: 'top_k', label: 'Search Candidates', description: 'Max cache entries returned by pgvector similarity search', min: 1, max: 20, step: 1, type: 'number' },
  { key: 'ttl_hours', label: 'Freshness TTL (hours)', description: 'Per-entry soft expiry — entries stop appearing in search after this window', min: 1, max: 720, step: 1, type: 'number' },
  { key: 'stale_days', label: 'Stale Window (days)', description: 'Evict entries not hit within this many days (keeps active entries alive)', min: 1, max: 90, step: 1, type: 'number' },
  { key: 'max_age_days', label: 'Max Age (days)', description: 'Hard eviction — delete entries older than this regardless of usage', min: 1, max: 365, step: 1, type: 'number' },
];

const MEMORY_FIELDS: FieldDef[] = [
  { key: 'similarity_threshold', label: 'Retrieval Threshold', description: 'Minimum similarity to surface a stored memory', min: 0.0, max: 1.0, step: 0.01, type: 'slider' },
  { key: 'score_threshold', label: 'Score Threshold', description: 'Minimum memory strength score to be eligible', min: 0.0, max: 1.0, step: 0.01, type: 'slider' },
  { key: 'blocklist_threshold', label: 'Blocklist Threshold', description: 'Similarity above this blocks duplicate memory creation', min: 0.5, max: 1.0, step: 0.01, type: 'slider' },
  { key: 'decay_rate', label: 'Decay Rate', description: 'How fast unused memories decay per cycle', min: 0.0, max: 0.5, step: 0.01, type: 'slider' },
  { key: 'top_k', label: 'Top K', description: 'Max memories retrieved per query', min: 1, max: 20, step: 1, type: 'number' },
  { key: 'max_age_days', label: 'Max Age (days)', description: 'Memories older than this are archived', min: 1, max: 365, step: 1, type: 'number' },
];

const LLM_FIELDS: FieldDef[] = [
  { key: 'assistant_endpoint', label: 'Assistant (Sonnet 4)', description: 'Summarization, SQL adaptation, morphing, rewriting, assistant', type: 'readonly' },
  { key: 'classifier_endpoint', label: 'Classifier (Haiku 4.5)', description: 'Intent classification, already-answered check, SQL validation', type: 'readonly' },
];

export default function ConfigPage() {
  const [cfg, setCfg] = useState<TuningConfig | null>(null);
  const [dirty, setDirty] = useState<Partial<TuningConfig>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ msg: string; type: 'success' | 'error' } | null>(null);

  const [spaces, setSpaces] = useState<GenieSpaceInfo[]>([]);

  const loadSpaces = useCallback(async () => {
    try {
      const data = await getActiveSpaces();
      setSpaces(data);
    } catch (e) {
      console.error('Failed to load spaces', e);
    }
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await getTuning();
      setCfg(data);
      setDirty({});
    } catch (e) {
      console.error('Failed to load config', e);
    }
    setLoading(false);
  }, []);

  useEffect(() => { load(); loadSpaces(); }, [load, loadSpaces]);

  const showToast = (msg: string, type: 'success' | 'error') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 3000);
  };

  const handleChange = (section: keyof TuningConfig, key: string, value: number) => {
    setDirty(prev => ({
      ...prev,
      [section]: { ...(prev[section] as any || {}), [key]: value },
    }));
  };

  const getVal = (section: keyof TuningConfig, key: string): number => {
    const d = dirty[section] as Record<string, number> | undefined;
    if (d && key in d) return d[key];
    return (cfg as any)?.[section]?.[key] ?? 0;
  };

  const isDirty = Object.keys(dirty).length > 0;

  const handleSave = async () => {
    if (!isDirty) return;
    setSaving(true);
    try {
      const result = await updateTuning(dirty);
      showToast(`Updated ${result.updated.length} setting(s)`, 'success');
      await load();
    } catch (e: any) {
      showToast(e.message || 'Save failed', 'error');
    }
    setSaving(false);
  };

  const handleReset = () => setDirty({});

  if (loading || !cfg) {
    return (
      <div>
        <div className="page-header"><h1>Configuration</h1><p>Loading...</p></div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Configuration</h1>
            <p>Tune similarity thresholds, memory settings, and LLM parameters live</p>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            {isDirty && (
              <button className="btn" onClick={handleReset}>Reset</button>
            )}
            <button
              className="btn btn-primary"
              onClick={handleSave}
              disabled={!isDirty || saving}
            >
              {saving ? 'Saving...' : isDirty ? 'Save Changes' : 'No Changes'}
            </button>
          </div>
        </div>
      </div>

      {toast && (
        <div style={{
          position: 'fixed', top: 20, right: 20, zIndex: 9999,
          padding: '10px 20px', borderRadius: 8,
          background: toast.type === 'success' ? 'var(--cache-hit)' : '#ef4444',
          color: '#fff', fontSize: 13, fontWeight: 600,
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
        }}>
          {toast.msg}
        </div>
      )}

      <Section title="Cache Thresholds" description="Control when cached queries are reused vs. sent to Genie">
        {CACHE_FIELDS.map(f => (
          <FieldRow key={f.key} field={f} value={getVal('cache', f.key)}
            changed={(dirty.cache as any)?.[f.key] != null}
            original={(cfg.cache as any)[f.key]}
            onChange={v => handleChange('cache', f.key, v)} />
        ))}
        <ThresholdVisualizer
          direct={getVal('cache', 'similarity_threshold')}
          template={getVal('cache', 'answer_morph_threshold')}
        />
      </Section>

      <Section title="Memory Settings" description="Control long-term memory retrieval and lifecycle">
        {MEMORY_FIELDS.map(f => (
          <FieldRow key={f.key} field={f} value={getVal('memory', f.key)}
            changed={(dirty.memory as any)?.[f.key] != null}
            original={(cfg.memory as any)[f.key]}
            onChange={v => handleChange('memory', f.key, v)} />
        ))}
      </Section>

      <Section title="Genie Spaces" description="Configured at deploy time via GENIE_SPACE_IDS in databricks.yml">
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {spaces.map(s => (
            <div key={s.space_id} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '10px 12px',
              background: 'var(--bg-input)', borderRadius: 8,
              border: '1px solid var(--border)',
            }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{s.title}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'monospace' }}>{s.space_id}</div>
                {s.description && <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{s.description}</div>}
              </div>
              {s.genie_room_url && (
                <a href={s.genie_room_url} target="_blank" rel="noreferrer"
                  style={{ fontSize: 11, color: 'var(--accent)', textDecoration: 'none' }}>
                  Open →
                </a>
              )}
            </div>
          ))}
          {spaces.length === 0 && (
            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 12, textAlign: 'center' }}>
              No Genie spaces configured. Set GENIE_SPACE_IDS in databricks.yml and redeploy.
            </div>
          )}
        </div>
      </Section>

      <Section title="LLM Settings" description="Model endpoints (all calls use temperature 0 for deterministic output)">
        {LLM_FIELDS.map(f => (
          f.type === 'readonly' ? (
            <div key={f.key} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '10px 0', borderBottom: '1px solid var(--border)' }}>
              <div>
                <div style={{ fontSize: 13, fontWeight: 600 }}>{f.label}</div>
                <div style={{ fontSize: 11, color: 'var(--text-secondary)' }}>{f.description}</div>
              </div>
              <code style={{ fontSize: 12, background: 'var(--bg-input)', padding: '4px 10px', borderRadius: 6 }}>
                {(cfg.llm as any)[f.key]}
              </code>
            </div>
          ) : (
            <FieldRow key={f.key} field={f} value={getVal('llm', f.key)}
              changed={(dirty.llm as any)?.[f.key] != null}
              original={(cfg.llm as any)[f.key]}
              onChange={v => handleChange('llm', f.key, v)} />
          )
        ))}
      </Section>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <h3 style={{ fontSize: 15, fontWeight: 700, marginBottom: 2 }}>{title}</h3>
      <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginBottom: 16 }}>{description}</p>
      {children}
    </div>
  );
}

function FieldRow({ field, value, changed, original, onChange }: {
  field: FieldDef; value: number; changed: boolean; original: number;
  onChange: (v: number) => void;
}) {
  const isSlider = field.type === 'slider';
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16, padding: '10px 0',
      borderBottom: '1px solid var(--border)',
    }}>
      <div style={{ flex: '0 0 200px' }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          {field.label}
          {changed && <span style={{ color: 'var(--accent)', marginLeft: 6, fontSize: 11 }}>modified</span>}
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-secondary)', lineHeight: 1.4 }}>{field.description}</div>
      </div>
      <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 12 }}>
        {isSlider && (
          <input
            type="range"
            min={field.min} max={field.max} step={field.step}
            value={value}
            onChange={e => onChange(parseFloat(e.target.value))}
            style={{ flex: 1, accentColor: 'var(--accent)' }}
          />
        )}
        <input
          type="number"
          min={field.min} max={field.max} step={field.step}
          value={isSlider ? value.toFixed(2) : value}
          onChange={e => onChange(parseFloat(e.target.value))}
          style={{
            width: isSlider ? 70 : 90, padding: '6px 10px', fontSize: 13,
            background: 'var(--bg-input)', border: `1px solid ${changed ? 'var(--accent)' : 'var(--border)'}`,
            borderRadius: 6, color: 'var(--text-primary)', textAlign: 'center',
          }}
        />
        {changed && (
          <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
            was {typeof original === 'number' && original % 1 !== 0 ? original.toFixed(2) : original}
          </span>
        )}
      </div>
    </div>
  );
}

function ThresholdVisualizer({ direct, template }: { direct: number; template: number }) {
  const zones = [
    { label: 'Miss', start: 0, end: template, color: 'var(--cache-miss)', opacity: 0.3 },
    { label: 'SQL Adapt', start: template, end: direct, color: '#f59e0b', opacity: 0.5 },
    { label: 'Direct Hit', start: direct, end: 1.0, color: 'var(--cache-hit)', opacity: 0.6 },
  ];

  return (
    <div style={{ marginTop: 16, padding: 16, background: 'var(--bg-input)', borderRadius: 10 }}>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: 'var(--text-secondary)' }}>
        Similarity Scale
      </div>
      <div style={{ position: 'relative', height: 32, borderRadius: 6, overflow: 'hidden', display: 'flex' }}>
        {zones.map(z => (
          <div key={z.label} style={{
            width: `${(z.end - z.start) * 100}%`, height: '100%',
            background: z.color, opacity: z.opacity,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 11, fontWeight: 600, color: '#fff',
          }}>
            {(z.end - z.start) > 0.08 ? z.label : ''}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 4, fontSize: 10, color: 'var(--text-muted)' }}>
        <span>0.0</span>
        <span style={{ position: 'relative', left: `${template * 50 - 50}%` }}>{template.toFixed(2)}</span>
        <span style={{ position: 'relative', left: `${direct * 50 - 50}%` }}>{direct.toFixed(2)}</span>
        <span>1.0</span>
      </div>
    </div>
  );
}
