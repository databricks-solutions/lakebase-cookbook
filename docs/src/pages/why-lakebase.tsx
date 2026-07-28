import React, { useEffect, useRef, useState } from "react";
import Link from "@docusaurus/Link";
import Layout from "@theme/Layout";

interface Feature {
  title: string;
  description: string;
}

const FEATURES: Feature[] = [
  {
    title: "Database branching and snapshots",
    description:
      "Create sub-second, copy-on-write clones of a database to test changes against production-like data without copying it. Branches give developers, CI pipelines, and AI agents a safe, isolated environment, and snapshots make it easy to capture and restore a known state.",
  },
  {
    title: "Autoscaling and scale-to-zero",
    description:
      "Compute and storage are separated and scale independently. Instances launch in under a second, scale with demand to support high concurrency, and can scale to zero when idle, so you pay only for what you use rather than for always-on provisioned capacity.",
  },
  {
    title: "Bidirectional lakehouse synchronization",
    description:
      "Automatically synchronize data to and from lakehouse tables. Serve analytical data to applications with low latency through synced tables, write operational data back to the lakehouse, and power an online feature store for model serving — all without building and maintaining custom ETL.",
  },
  {
    title: "Native PostgreSQL",
    description:
      "Lakebase is built on the open-source PostgreSQL engine, so it works with the tools, drivers, and extensions your teams already use — including pgvector for embeddings. There is no proprietary dialect to learn and no lock-in to a bespoke API.",
  },
  {
    title: "Disaster recovery and resilience",
    description:
      "Announced at the Data + AI Summit, Lakebase supports cross-region and cross-cloud disaster recovery with one-step failover. Combined with high availability, point-in-time recovery, and encryption at rest, it provides the resilience that mission-critical applications and agents require.",
  },
  {
    title: "Lower total cost of ownership",
    description:
      "Lakebase is fully managed with usage-based pricing and scale-to-zero, removing the operational burden of running database infrastructure. By unifying operational and analytical data on the lakehouse, it also eliminates the replicas and pipelines that drive up the cost of database ownership.",
  },
];

const pad = (n: number) => String(n).padStart(2, "0");

function FeatureScroller() {
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
      // Active when a section sits in the middle band of the viewport.
      { rootMargin: "-45% 0px -45% 0px", threshold: 0 },
    );
    sectionRefs.current.forEach((el) => el && observer.observe(el));
    return () => observer.disconnect();
  }, []);

  const goTo = (i: number) =>
    sectionRefs.current[i]?.scrollIntoView({
      behavior: "smooth",
      block: "center",
    });

  return (
    <div className="relative grid grid-cols-1 gap-8 lg:grid-cols-[300px_1fr] lg:gap-16">
      {/* Sticky progress rail (desktop) */}
      <nav className="hidden lg:block">
        <div className="sticky top-28 flex flex-col gap-1">
          <div className="mb-4 text-xs font-semibold tracking-widest text-gray-400 uppercase">
            Capabilities
          </div>
          {FEATURES.map((feature, i) => (
            <button
              key={feature.title}
              onClick={() => goTo(i)}
              className={`flex items-baseline gap-3 border-l-4 py-2 pl-4 text-left text-sm font-semibold transition-all duration-300 hover:cursor-pointer ${
                i === active
                  ? "border-lava-600 bg-[#F9F7F4] text-[#1B3139] dark:bg-[#242526] dark:text-white"
                  : "border-transparent text-gray-400 hover:text-gray-600 dark:hover:text-gray-300"
              }`}
            >
              <span className="tabular-nums">{pad(i + 1)}</span>
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
            className={`flex min-h-[55vh] flex-col justify-center border-l-4 py-10 pl-6 transition-all duration-500 motion-reduce:opacity-100 lg:min-h-[70vh] lg:pl-10 ${
              i === active
                ? "border-lava-600 opacity-100"
                : "border-gray-200 opacity-45 dark:border-gray-700"
            }`}
          >
            <div
              className={`mb-3 text-sm font-semibold tracking-widest text-lava-600 transition-opacity duration-500 motion-reduce:opacity-100 ${
                i === active ? "opacity-100" : "opacity-0"
              }`}
            >
              {pad(i + 1)} / {pad(FEATURES.length)}
            </div>
            <h2 className="mb-4 text-3xl font-bold text-[#1B3139] sm:text-4xl dark:text-white">
              {feature.title}
            </h2>
            <p className="max-w-2xl text-lg leading-relaxed text-gray-700 dark:text-gray-300">
              {feature.description}
            </p>
          </div>
        ))}
      </div>
    </div>
  );
}

function WhyLakebasePage() {
  return (
    <Layout
      title="Why Lakebase"
      description="Why Lakebase: a fully managed, Postgres-compatible operational database built into the lakehouse to lower the total cost of database ownership."
    >
      <div className="px-4 py-10 sm:px-6 sm:py-14">
        <div className="container mx-auto max-w-6xl">
          {/* Hero */}
          <div className="mx-auto mb-16 max-w-3xl text-center">
            <h1 className="mb-4 text-4xl font-bold sm:text-5xl">Why Lakebase</h1>
            <p className="text-lg text-gray-700 dark:text-gray-300">
              Lakebase is a fully managed, PostgreSQL-compatible operational
              database built directly into the lakehouse. It brings transactional
              workloads and analytical data together on one governed platform,
              reducing the complexity and cost of running a separate operational
              database. Scroll to explore what sets it apart.
            </p>
          </div>

          {/* Scrollytelling feature section */}
          <FeatureScroller />

          {/* TCO highlight band */}
          <div className="mt-16 border-l-4 border-lava-600 bg-[#1B3139] p-8 text-white sm:p-10">
            <h2
              className="mb-3 text-2xl font-bold sm:text-3xl"
              style={{ color: "#ffffff" }}
            >
              Lowering the total cost of database ownership
            </h2>
            <p className="max-w-4xl text-base leading-relaxed text-gray-200 sm:text-lg">
              Traditional operational databases require dedicated infrastructure,
              always-on capacity, and pipelines to move data into the analytics
              platform. Lakebase replaces that with a fully managed service that
              scales to zero, charges only for what you use, and keeps operational
              and analytical data on a single governed copy — so teams spend less
              on infrastructure, data movement, and operational overhead.
            </p>
          </div>

          {/* CTA */}
          <div className="mt-12 flex flex-col items-stretch justify-center gap-4 sm:flex-row sm:items-center">
            <Link to="/docs/category/examples" className="w-full sm:w-auto">
              <button className="w-full border-2 border-lava-700 bg-lava-700 px-8 py-2.5 font-semibold text-white hover:cursor-pointer hover:border-lava-800 hover:bg-lava-800 hover:underline">
                Browse Examples
              </button>
            </Link>
            <Link to="/docs/intro" className="w-full sm:w-auto">
              <button className="w-full border-2 border-gray-800 bg-transparent px-8 py-2.5 font-semibold text-gray-800 hover:cursor-pointer hover:underline dark:border-white dark:text-white">
                Read the docs
              </button>
            </Link>
            <a
              href="https://www.databricks.com/product/lakebase"
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto"
            >
              <button className="w-full border-2 border-gray-800 bg-transparent px-8 py-2.5 font-semibold text-gray-800 hover:cursor-pointer hover:underline dark:border-white dark:text-white">
                Lakebase product page
              </button>
            </a>
          </div>
        </div>
      </div>
    </Layout>
  );
}

export default WhyLakebasePage;
