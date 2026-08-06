import { useState, useEffect } from 'react'
import { getMetrics, Metrics } from '../api'

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [loading, setLoading] = useState(true);

  const EMPTY_METRICS: Metrics = {
    total_queries: 0, cache_hits: 0, cache_misses: 0, cache_rejections: 0,
    hit_rate: 0, avg_latency_hit_ms: 0, avg_latency_miss_ms: 0,
    latency_savings_ms: 0, cache_size: 0,
  };

  const loadMetrics = async () => {
    setLoading(true);
    try {
      const data = await getMetrics();
      setMetrics(data?.total_queries != null ? data : EMPTY_METRICS);
    } catch (err) {
      console.error('Failed to load metrics', err);
      setMetrics(EMPTY_METRICS);
    }
    setLoading(false);
  };

  useEffect(() => { loadMetrics(); }, []);

  if (loading || !metrics) {
    return (
      <div>
        <div className="page-header">
          <h1>Performance Metrics</h1>
          <p>Loading...</p>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Performance Metrics</h1>
            <p>Cache performance, latency savings, and usage statistics</p>
          </div>
          <button className="btn" onClick={loadMetrics}>Refresh</button>
        </div>
      </div>

      <div className="stat-grid">
        <div className="stat-card">
          <div className="label">Total Queries</div>
          <div className="value accent">{metrics.total_queries}</div>
        </div>
        <div className="stat-card">
          <div className="label">Cache Hit Rate</div>
          <div className="value success">{(metrics.hit_rate * 100).toFixed(1)}%</div>
        </div>
        <div className="stat-card">
          <div className="label">Cache Size</div>
          <div className="value">{metrics.cache_size}</div>
        </div>
        <div className="stat-card">
          <div className="label">Latency Savings</div>
          <div className="value success">{metrics.latency_savings_ms.toFixed(0)}ms</div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 24 }}>
        <div className="card">
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>Cache Breakdown</h3>
          <div style={{ display: 'flex', gap: 24 }}>
            <div style={{ flex: 1 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Hits</span>
                <span className="badge hit">{metrics.cache_hits}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Misses</span>
                <span className="badge miss">{metrics.cache_misses}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>Rejected</span>
                <span className="badge rejected">{metrics.cache_rejections}</span>
              </div>
            </div>
            <div style={{ flex: 1 }}>
              <CacheBar
                hits={metrics.cache_hits}
                misses={metrics.cache_misses}
                rejections={metrics.cache_rejections}
              />
            </div>
          </div>
        </div>

        <div className="card">
          <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>Latency Comparison</h3>
          <LatencyBars hit={metrics.avg_latency_hit_ms} miss={metrics.avg_latency_miss_ms} />
        </div>
      </div>

      <div className="card">
        <h3 style={{ fontSize: 14, fontWeight: 600, marginBottom: 16 }}>How It Works</h3>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          {[
            { step: '1', title: 'Rewrite Query', desc: 'Multi-turn context resolved to standalone question' },
            { step: '2', title: 'Semantic Search', desc: 'pgvector cosine similarity against cached queries' },
            { step: '3', title: 'Validate & Execute', desc: 'Cached SQL executed on warehouse; Genie fallback on miss' },
            { step: '4', title: 'Learn & Cache', desc: 'Thumbs-up feedback promotes successful queries to cache' },
          ].map(s => (
            <div key={s.step} style={{
              padding: 16, background: 'var(--bg-input)', borderRadius: 10,
              border: '1px solid var(--border)'
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: '50%',
                background: 'var(--accent)', display: 'flex',
                alignItems: 'center', justifyContent: 'center',
                fontSize: 14, fontWeight: 700, marginBottom: 8
              }}>{s.step}</div>
              <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4 }}>{s.title}</div>
              <div style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.5 }}>{s.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function CacheBar({ hits, misses, rejections }: { hits: number; misses: number; rejections: number }) {
  const total = hits + misses + rejections;
  if (total === 0) return <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>No data yet</div>;
  return (
    <div>
      <div style={{
        display: 'flex', height: 24, borderRadius: 6, overflow: 'hidden',
        background: 'var(--bg-primary)'
      }}>
        {hits > 0 && <div style={{ width: `${hits/total*100}%`, background: 'var(--cache-hit)' }} />}
        {misses > 0 && <div style={{ width: `${misses/total*100}%`, background: 'var(--cache-miss)' }} />}
        {rejections > 0 && <div style={{ width: `${rejections/total*100}%`, background: 'var(--cache-rejected)' }} />}
      </div>
      <div style={{ display: 'flex', justifyContent: 'center', gap: 16, marginTop: 8, fontSize: 11 }}>
        <span style={{ color: 'var(--cache-hit)' }}>Hit {(hits/total*100).toFixed(0)}%</span>
        <span style={{ color: 'var(--cache-miss)' }}>Miss {(misses/total*100).toFixed(0)}%</span>
        <span style={{ color: 'var(--cache-rejected)' }}>Reject {(rejections/total*100).toFixed(0)}%</span>
      </div>
    </div>
  );
}

function LatencyBars({ hit, miss }: { hit: number; miss: number }) {
  const max = Math.max(hit, miss, 1);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
          <span style={{ color: 'var(--text-secondary)' }}>Cache Hit</span>
          <span style={{ color: 'var(--cache-hit)', fontWeight: 600 }}>{hit.toFixed(0)}ms</span>
        </div>
        <div style={{
          height: 12, borderRadius: 6, overflow: 'hidden',
          background: 'var(--bg-primary)'
        }}>
          <div style={{
            width: `${hit/max*100}%`, height: '100%', borderRadius: 6,
            background: 'var(--cache-hit)', transition: 'width 0.3s'
          }} />
        </div>
      </div>
      <div>
        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4, fontSize: 12 }}>
          <span style={{ color: 'var(--text-secondary)' }}>Cache Miss (Genie)</span>
          <span style={{ color: 'var(--cache-miss)', fontWeight: 600 }}>{miss.toFixed(0)}ms</span>
        </div>
        <div style={{
          height: 12, borderRadius: 6, overflow: 'hidden',
          background: 'var(--bg-primary)'
        }}>
          <div style={{
            width: `${miss/max*100}%`, height: '100%', borderRadius: 6,
            background: 'var(--cache-miss)', transition: 'width 0.3s'
          }} />
        </div>
      </div>
    </div>
  );
}
