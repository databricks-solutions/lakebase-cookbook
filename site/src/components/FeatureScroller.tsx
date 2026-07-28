import { useEffect, useRef, useState } from 'react';

interface Feature {
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    title: 'Database branching and snapshots',
    description:
      'Create sub-second, copy-on-write clones of a database to test changes against production-like data without copying it. Branches give developers, CI pipelines, and AI agents a safe, isolated environment, and snapshots make it easy to capture and restore a known state.',
  },
  {
    title: 'Autoscaling and scale-to-zero',
    description:
      'Compute and storage are separated and scale independently. Instances launch in under a second, scale with demand to support high concurrency, and can scale to zero when idle, so you pay only for what you use rather than for always-on provisioned capacity.',
  },
  {
    title: 'Bidirectional lakehouse synchronization',
    description:
      'Automatically synchronize data to and from lakehouse tables. Serve analytical data to applications with low latency through synced tables, write operational data back to the lakehouse, and power an online feature store for model serving — all without building and maintaining custom ETL.',
  },
  {
    title: 'Native PostgreSQL',
    description:
      'Lakebase is built on the open-source PostgreSQL engine, so it works with the tools, drivers, and extensions your teams already use — including pgvector for embeddings. There is no proprietary dialect to learn and no lock-in to a bespoke API.',
  },
  {
    title: 'Disaster recovery and resilience',
    description:
      'Announced at the Data + AI Summit, Lakebase supports cross-region and cross-cloud disaster recovery with one-step failover. Combined with high availability, point-in-time recovery, and encryption at rest, it provides the resilience that mission-critical applications and agents require.',
  },
  {
    title: 'Lower total cost of ownership',
    description:
      'Lakebase is fully managed with usage-based pricing and scale-to-zero, removing the operational burden of running database infrastructure. By unifying operational and analytical data on the lakehouse, it also eliminates the replicas and pipelines that drive up the cost of database ownership.',
  },
];

const pad = (n: number) => String(n).padStart(2, '0');

export default function FeatureScroller() {
  const [active, setActive] = useState(0);
  const sectionRefs = useRef<(HTMLDivElement | null)[]>([]);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const idx = Number((entry.target as HTMLElement).dataset.index);
            setActive(idx);
          }
        });
      },
      { rootMargin: '-40% 0px -40% 0px', threshold: 0 },
    );
    sectionRefs.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const goTo = (i: number) =>
    sectionRefs.current[i]?.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
    });

  return (
    <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[300px_1fr] lg:gap-16">
      {/* Sticky progress rail (desktop) */}
      <nav className="hidden lg:block">
        <div className="sticky top-28 flex flex-col gap-1">
          <div className="mono-label mb-4 text-[0.7rem] text-[var(--color-muted)]">
            Capabilities
          </div>
          {FEATURES.map((feature, i) => (
            <button
              key={feature.title}
              onClick={() => goTo(i)}
              className={`flex items-baseline gap-3 border-l-2 py-2 pl-4 text-left text-sm font-semibold transition-all duration-300 hover:cursor-pointer ${
                i === active
                  ? 'border-[var(--color-lava-600)] bg-[var(--color-band)] text-[var(--color-ink)]'
                  : 'border-[var(--color-line)] text-[var(--color-muted)] hover:text-[var(--color-ink)]'
              }`}
            >
              <span className="mono-label tabular-nums text-[0.7rem]">
                {pad(i + 1)}
              </span>
              <span>{feature.title}</span>
            </button>
          ))}
        </div>
      </nav>

      {/* Scroll-activated feature sections */}
      <div className="flex flex-col">
        {FEATURES.map((feature, i) => (
          <div
            key={feature.title}
            data-index={i}
            ref={(el) => {
              sectionRefs.current[i] = el;
            }}
            className={`flex min-h-[32vh] flex-col justify-center border-l-2 py-8 pl-6 transition-all duration-500 motion-reduce:opacity-100 lg:min-h-[40vh] lg:pl-10 ${
              i === active
                ? 'border-[var(--color-lava-600)] opacity-100'
                : 'border-[var(--color-line)] opacity-45'
            }`}
          >
            <div
              className={`mono-label mb-3 text-[0.7rem] text-[var(--color-lava-600)] transition-opacity duration-500 motion-reduce:opacity-100 ${
                i === active ? 'opacity-100' : 'opacity-0'
              }`}
            >
              {pad(i + 1)} / {pad(FEATURES.length)}
            </div>
            <h2 className="mb-4 text-3xl font-light tracking-tight text-[var(--color-ink)] sm:text-4xl">
              {feature.title}
            </h2>
            <p className="max-w-2xl text-lg leading-relaxed text-[var(--color-muted)]">
              {feature.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}
