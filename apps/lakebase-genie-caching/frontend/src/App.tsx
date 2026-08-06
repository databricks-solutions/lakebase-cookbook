import { Component, ReactNode, useEffect, useState, useMemo } from 'react'
import { Routes, Route, NavLink, useLocation, useSearchParams } from 'react-router-dom'
import ChatPage from './pages/ChatPage'
import CachePage from './pages/CachePage'
import MemoryPage from './pages/MemoryPage'
import MetricsPage from './pages/MetricsPage'
import ConfigPage from './pages/ConfigPage'
import { AppConfig, getConfig } from './api'
import './App.css'

class ErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean; error?: Error }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(error: Error) {
    return { hasError: true, error };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{
          padding: 40, textAlign: 'center',
          color: 'var(--text-secondary)', maxWidth: 500, margin: '80px auto',
        }}>
          <h2 style={{ color: 'var(--text-primary)', marginBottom: 12 }}>Something went wrong</h2>
          <p style={{ fontSize: 14, marginBottom: 16 }}>
            {this.state.error?.message || 'An unexpected error occurred.'}
          </p>
          <button
            className="btn btn-primary"
            onClick={() => this.setState({ hasError: false, error: undefined })}
          >
            Try Again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function LocationErrorBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
}

function App() {
  const [cfg, setCfg] = useState<AppConfig | null>(null);
  const [searchParams] = useSearchParams();
  const isAdmin = useMemo(() => searchParams.get('admin') === 'true', [searchParams]);

  useEffect(() => {
    getConfig().then(setCfg);
  }, []);

  return (
    <div className="app">
      <nav className="sidebar">
        <div className="logo">
          <svg width="28" height="28" viewBox="0 0 28 28" fill="none">
            <rect width="28" height="28" rx="8" fill="var(--accent)" />
            <path d="M8 14l4 4 8-8" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <span>Genie Cache</span>
        </div>
        <div className="nav-links">
          <NavLink to="/" end className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            <ChatIcon /> Chat
          </NavLink>
          <NavLink to="/cache" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            <CacheIcon /> Cache
          </NavLink>
          <NavLink to="/memory" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            <MemoryIcon /> Memory
          </NavLink>
          <NavLink to="/metrics" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
            <MetricsIcon /> Metrics
          </NavLink>
          {isAdmin && (
            <NavLink to="/config" className={({ isActive }) => isActive ? 'nav-link active' : 'nav-link'}>
              <ConfigIcon /> Config
            </NavLink>
          )}
        </div>
        {cfg && (
          <div className="resources-section">
            <div className="resources-label">RESOURCES</div>
            <ResourceLink href={cfg.resource_links.mlflow_traces} label="MLflow Traces" />
            <ResourceLink href={cfg.resource_links.lakebase} label="Lakebase" />
            <ResourceLink href={cfg.resource_links.trace_archive_table} label="Trace Archive Table" />
            <ResourceLink href={cfg.resource_links.trace_archive_job} label="Trace Archive Job" />
            <ResourceLink href={cfg.resource_links.batch_pipelines_job} label="Cache/Memory Job" />
          </div>
        )}
        <div className="sidebar-footer">
          <span className="version">v0.1.0</span>
        </div>
      </nav>
      <main className="main-content">
        <LocationErrorBoundary>
          <Routes>
            <Route path="/" element={<ChatPage />} />
            <Route path="/cache" element={<CachePage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/metrics" element={<MetricsPage />} />
            <Route path="/config" element={<ConfigPage />} />
          </Routes>
        </LocationErrorBoundary>
      </main>
    </div>
  )
}

function ChatIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z"/></svg>
}
function CacheIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 2L2 7l10 5 10-5-10-5z"/><path d="M2 17l10 5 10-5"/><path d="M2 12l10 5 10-5"/></svg>
}
function MemoryIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>
}
function MetricsIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>
}
function ConfigIcon() {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09a1.65 1.65 0 00-1.08-1.51 1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09a1.65 1.65 0 001.51-1.08 1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001.08 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1.08z"/></svg>
}
function ExternalLinkIcon() {
  return <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
}
function ResourceLink({ href, label }: { href: string | null; label: string }) {
  if (!href) return null;
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className="resource-link">
      {label} <ExternalLinkIcon />
    </a>
  )
}

export default App
