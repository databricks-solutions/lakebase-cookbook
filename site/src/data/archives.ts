export type MediaType = 'Video' | 'Blog' | 'Customer Story' | 'Announcement';

export interface ArchiveEntry {
  title: string;
  mediaType: MediaType;
  source: string;
  date: string;
  url: string;
  summary: string;
}

// To add an entry, append to this list and open a pull request.
//
// Customer story pages on databricks.com carry no publish date. Their `date`
// is estimated from the month the page's own images were uploaded
// (/sites/default/files/YYYY-MM/), which matches Wayback Machine first captures
// and Databricks Community announcements wherever those exist.
export const ARCHIVE: ArchiveEntry[] = [
  {
    title: 'Enabling Evolutionary Database Development: database branching with Lakebase',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'May 2026',
    url: 'https://www.databricks.com/blog/enabling-evolutionary-database-development-database-branching-lakebase',
    summary:
      'Part 1 of a three-part series with Pramod Sadalage (Thoughtworks). Follows one developer through a single feature and its database change, showing how a per-developer Lakebase branch — a fast, realistic, isolated copy of production — turns database change from a bottleneck into a normal part of feature development, finally making "everybody gets their own database instance" operational.',
  },
  {
    title: 'Enabling Evolutionary Database Development: database branching with Lakebase, continued',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/enabling-evolutionary-database-development-database-branching-lakebase-part-2',
    summary:
      'Part 2 of the series. Copy-on-write branching restores the original seven evolutionary-database practices as routine and unlocks two new ones — destructive testing and A/B schema prototyping at the database level — all inside the standard CI/CD pipeline without sacrificing rigor or governance.',
  },
  {
    title: 'Enabling Evolutionary Database Development: Database branching with Lakebase, the conclusion',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/enabling-evolutionary-database-development-database-branching-lakebase-part-3',
    summary:
      'Part 3 of the series. At team scale, tiers become long-running branches, governance is designed once and inherited per branch, and agents work inside the same policy-enforced substrate as humans — letting a large team plus agent fleets collaborate on a unified, governed database.',
  },
  {
    title: 'From monolith to Lakebase to LTAP: rethinking the database from storage up',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/lakebase-ltap-rethinking-database-storage',
    summary:
      'Reynold Xin walks through how Lakebase re-architects the database by separating compute from storage — externalizing the write-ahead log and data files into independent SafeKeeper and PageServer services — and introduces LTAP (Lake Transactional/Analytical Processing), which unifies transactions and analytics on a single copy of data at the storage layer.',
  },
  {
    title: 'Inside Lakebase: fully-managed serverless Postgres',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=NqJIyP9rIW8',
    summary:
      'Nikita Shamgunov (VP Engineering, Databricks) introduces Lakebase — a fully-managed, serverless Postgres built natively into the lakehouse — and walks through its architecture: serverless autoscaling, instant branching and rollback, Unity Catalog / Delta integration for zero-ETL access, and cross-cloud disaster recovery.',
  },
  {
    title: 'Safe AI-Driven Development with Lakebase Branches',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=jLX5LBzEDGc',
    summary:
      'A demo of Lakebase’s Git-like, zero-copy database branching: isolated, low-cost sandboxes for schema changes, agentic experimentation, and branch-based CI/CD, letting AI agents safely test against production-like data before promoting changes to production.',
  },
  {
    title: 'How Mastercard standardizes on Lakebase to power agentic operations',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=oyl2XgCpW7E',
    summary:
      'A customer session on how Mastercard standardizes on Lakebase as the operational database powering its agentic workloads, unifying transactional apps and analytics on one governed platform.',
  },
  {
    title: 'Announcing Lakebase Search: agent-native retrieval built into Lakebase Postgres',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/blog/announcing-lakebase-search-agent-native-retrieval-built-lakebase-postgres',
    summary:
      'Introduces Lakebase Search — hybrid vector and full-text retrieval built into Lakebase Postgres via the native lakebase_vector and lakebase_text extensions — so agents can retrieve context, reason, act, and remember on a single Postgres backend without a separate vector database.',
  },
  {
    title: 'AI Agents That Remember: Building Stateful Systems with Lakebase',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'May 2026',
    url: 'https://www.youtube.com/watch?v=UrIybbk-aY4',
    summary:
      'A walkthrough of using Lakebase as durable memory for AI agents — giving stateful systems persistent, queryable storage for conversation history, facts, and embeddings on managed Postgres.',
  },
  {
    title: 'Data + AI Summit 2026 Keynote — Day 1',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=Qux8E-L1mk8',
    summary:
      'The Data + AI Summit day-one keynote, where Databricks leaders presented the latest Lakebase capabilities, including cross-region and cross-cloud disaster recovery, alongside live product demos.',
  },
  {
    title: 'A New Era of Databases: Lakebase',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/what-is-a-lakebase',
    summary:
      'The foundational explainer for Lakebase: what a lakebase is, why separating compute from storage on open formats matters, and how it unifies operational and analytical data.',
  },
  {
    title:
      'Databricks Launches Lakebase: a New Class of Operational Database for AI Apps and Agents',
    mediaType: 'Announcement',
    source: 'Databricks Newsroom',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/company/newsroom/press-releases/databricks-launches-lakebase-new-class-operational-database-ai-apps',
    summary:
      "The official launch announcement detailing Lakebase's branching, autoscaling, low-latency high-concurrency performance, and synchronization to and from the lakehouse.",
  },
  {
    title: 'Announcing Lakebase Public Preview',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/announcing-lakebase-public-preview',
    summary:
      'The public preview announcement, walking through how to get started with Lakebase and the core developer experience.',
  },
  {
    title: 'Databricks Lakebase is now Generally Available',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Feb 2026',
    url: 'https://www.databricks.com/blog/databricks-lakebase-generally-available',
    summary:
      'The general availability milestone for Lakebase, covering production readiness and the capabilities available to all customers.',
  },
  {
    title: 'How the Lakebase Architecture Stays Resilient to Cloud Failures',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: '2025',
    url: 'https://www.databricks.com/blog/how-lakebase-architecture-stays-resilient-cloud-failures',
    summary:
      'A deep dive into the resilience of the Lakebase architecture and how it maintains availability and durability through cloud failures.',
  },
  {
    title: 'Announcing Databricks Lakebase Launch Partners',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jun 2025',
    url: 'https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners',
    summary:
      'An overview of the ecosystem of launch partners building on and integrating with Lakebase.',
  },
  {
    title:
      'Databricks Launches LTAP: The First Lake Transactional/Analytical Processing Architecture',
    mediaType: 'Announcement',
    source: 'Databricks Newsroom',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/company/newsroom/press-releases/databricks-launches-ltap-first-lake-transactionalanalytical',
    summary:
      'The announcement of LTAP, unifying transactions, analytics, streaming, and operational data on a single governed copy of storage — the architecture Lakebase builds on.',
  },
  {
    title:
      'Branching databases like code: a CI/CD pattern for Lakebase, in production at Glaspoort',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/blog/branching-databases-code-cicd-pattern-lakebase-production-glaspoort',
    summary:
      'How Glaspoort runs a CI/CD pattern on Lakebase by branching every long-lived environment directly from production and treating database migrations as the source of truth, creating ephemeral per-PR branches tested against production-shaped data before changes are promoted.',
  },
  {
    title: 'Take Control: Customer-Managed Keys for Lakebase Postgres',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Apr 2026',
    url: 'https://www.databricks.com/blog/take-control-customer-managed-keys-lakebase-postgres',
    summary:
      'Introduces customer-managed keys (CMK) for Lakebase Postgres, using hierarchical envelope encryption to protect both persistent storage and ephemeral compute with keys held in your own cloud KMS — including key revocation that can render data cryptographically inaccessible for regulated workloads.',
  },
  {
    title: 'Unlock seamless and cost-effective marketing campaigns with Lakebase',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'May 2026',
    url: 'https://www.databricks.com/blog/unlock-seamless-and-cost-effective-marketing-campaigns-lakebase',
    summary:
      'Shows how Lakebase serves as the serverless OLTP database behind marketing platforms such as SAP Engagement Cloud, cutting total cost of ownership by scaling to zero during idle periods and removing manual sync pipelines through native synced tables.',
  },
  {
    title: "Beyond Provisioning: The Developer's Guide to Databricks Lakebase Autoscaling",
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Mar 2026',
    url: 'https://www.databricks.com/blog/beyond-provisioning-developers-guide-databricks-lakebase-autoscaling',
    summary:
      'A developer-focused guide to Lakebase autoscaling: how compute units adjust dynamically to CPU, memory, and working-set size, how to set min/max scaling boundaries, and how pairing autoscaling with scale-to-zero can cut compute costs by 70% or more for bursty workloads.',
  },
  {
    title: 'Zero-Downtime Patching in Lakebase Part 1: Prewarming',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Mar 2026',
    url: 'https://www.databricks.com/blog/zero-downtime-patching-lakebase-part-1-prewarming',
    summary:
      'Explains how Lakebase avoids performance drops during planned maintenance by prewarming a new compute node in the background — preloading its cache from the current primary’s page list and WAL stream before promotion — so throughput recovers almost instantly instead of suffering a cold-restart hit.',
  },
  {
    title: 'Simplify AI agent orchestration with Lakebase Postgres',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/blog/simplify-ai-agent-orchestration-lakebase-postgres',
    summary:
      'Built with CLA (CliftonLarsonAllen) for an agentic auditing app that cuts document extraction from hours to minutes. Shows how a pair of Lakebase tables becomes a durable, concurrent, crash-resilient task queue for long-running agent work — no broker, cache, or scheduler — with Postgres LISTEN/NOTIFY and Server-Sent Events driving a real-time operator dashboard.',
  },
  {
    title: 'Backstage with Lakebase, part 3',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/blog/backstage-lakebase-part-3',
    summary:
      'The finale of the Backstage series. Joins the live Backstage ownership graph in Lakebase with warehouse billing data through Lakehouse Federation to answer “who owns this cloud spend?” without an ETL pipeline, relying on per-workload compute isolation to keep the portal fast — plus the SCRAM-auth workaround federation currently needs.',
  },
  {
    title: 'Electric joins Databricks to bring WASM Postgres to AI agent sandboxes',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/blog/electric-joins-databricks-bring-wasm-postgres-ai-agent-sandboxes',
    summary:
      'Announces that Electric is joining Databricks. Its PGlite gives every agent a lightweight WASM Postgres right inside its sandbox, and its real-time sync engine keeps that distributed state synchronized back to a central Lakebase — extending Databricks’ Postgres from the lakehouse to the edge.',
  },
  {
    title: 'Object Storage + WAL: Lakebase Postgres for the agentic era',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/blog/object-storage-wal-lakebase-postgres-agentic-era',
    summary:
      'Explains why Lakebase treats the write-ahead log on object storage as the source of truth. Replacing physical data copies with lightweight pointers to log sequence numbers makes branching, point-in-time restore, and time-travel queries instant, while an immutable history in open columnar formats lets transactional and analytical engines read one dataset.',
  },
  {
    title: 'Vertical Advantage: Transforming Industries with Lakebase and Agentic AI',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/blog/vertical-advantage-transforming-industries-lakebase-and-agentic-ai',
    summary:
      'A tour of production-ready, industry-specific solutions that consulting and SI partners have built on Lakebase — from regulatory-change and fraud agents to real-time claims, prior authorization, dynamic pricing, and grid intelligence — across financial services, manufacturing, retail, healthcare, the public sector, and more.',
  },
  {
    title:
      'Building for the AI Era: Lakebase, Streaming, and Lakehouse Innovations at VLDB 2026',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/blog/building-ai-era-lakebase-streaming-and-lakehouse-innovations-vldb-2026',
    summary:
      'A preview of Databricks at VLDB 2026: Reynold Xin’s opening keynote on “The Three Golden Ages of Database Engineering,” introducing Lakebase and LTAP as the paradigms AI agents need, plus four accepted papers spanning Lakebase, Structured Streaming, and automatic lakehouse optimizations.',
  },
  {
    title: 'Autoscaling Lakebase Postgres',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/blog/autoscaling-lakebase-postgres',
    summary:
      'An engineering look at how Lakebase removes instance sizing. Because compute holds no durable state, a node can resize without moving the database, and in-place VM resizing driven by an algorithm that tracks CPU, memory, and working-set size adjusts capacity without stopping Postgres.',
  },
  {
    title:
      'The 40-year-old database rule agents just broke: How LTAP unifies OLTP and OLAP workloads',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Sep 2026',
    url: 'https://www.databricks.com/blog/40-year-old-database-rule-agents-just-broke-how-ltap-unifies-oltp-and-olap-workloads',
    summary:
      'A conversation with longtime Postgres contributor Jonathan Katz on why operational and analytical systems split apart, why AI agents acting on live state break that arrangement, and why LTAP succeeds where HTAP stalled — by unifying the two at the storage layer rather than inside a single engine.',
  },
  {
    title: 'Build durable agents with Temporal and Lakebase',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Sep 2026',
    url: 'https://www.databricks.com/blog/build-durable-agents-temporal-and-lakebase',
    summary:
      'A reference implementation of a personal-loan underwriting agent that may wait days for human review. Temporal provides durable execution across worker failures and retries, Lakebase holds queryable operational state, synced tables bring Unity Catalog policy in, and Change Data Feed publishes decisions back to Delta history tables.',
  },
  {
    title: 'Improving Lakebase Postgres compute cache',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Sep 2026',
    url: 'https://www.databricks.com/blog/improving-lakebase-postgres-compute-cache',
    summary:
      'How Lakebase reworked compute-side caching for its disaggregated storage: an autoscaling cache that works in tandem with Postgres shared buffers to keep as much data as possible on compute. In production, large compute nodes see up to 2x throughput, fewer reads from the storage layer, and lower latency.',
  },
  {
    title: 'Managed Postgres: What Lakebase Actually Takes Off Your Plate',
    mediaType: 'Blog',
    source: 'Databricks Blog',
    date: 'Sep 2026',
    url: 'https://www.databricks.com/blog/managed-postgres',
    summary:
      'Defines what “managed” should mean for Postgres and maps exactly what Lakebase automates — patching, autoscaling, scale-to-zero, failover, backups, point-in-time recovery, and branching — and where responsibility still sits with you, such as cross-region disaster recovery procedures.',
  },
  {
    title: 'Introducing Lakebase — Reynold Xin',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2025',
    url: 'https://www.youtube.com/watch?v=waGy8eYJvMg',
    summary:
      'Ali Ghodsi introduces Databricks co-founder and Chief Architect Reynold Xin, who unveils Lakebase: a fully-managed, Postgres-compatible transactional database that combines familiar Postgres with the scalability of the lakehouse and Neon’s database branching, built for developers and AI agents.',
  },
  {
    title: 'Lakebase: Fully Managed Postgres for the Lakehouse',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jul 2025',
    url: 'https://www.youtube.com/watch?v=3Bmnku-x0Yo',
    summary:
      'A session on how Lakebase supports intelligent applications with built-in lakehouse table synchronization that removes custom ETL, sub-10ms latency for high-throughput workloads, and full Postgres compatibility — with key capabilities and example use cases for data engineers and app developers.',
  },
  {
    title: 'Introduction to Lakebase: OLTP for Data Apps and AI Agents',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Dec 2025',
    url: 'https://www.youtube.com/watch?v=UQynsu6qklw',
    summary:
      'A short introduction to what Lakebase is, the OLTP–OLAP gap it bridges, and what serverless Postgres enables, followed by a Casper’s Kitchen demo walkthrough and a reverse ETL example for data apps, internal tools, and AI agents.',
  },
  {
    title: 'Lakebase: Postgres That Actually Likes Your Lakehouse',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Apr 2026',
    url: 'https://www.youtube.com/watch?v=EoWiK195fLc',
    summary:
      'Grant Doyle explains why Lakebase exists: how analytical and transactional systems evolved in separate silos, why the brittle ETL “bridges” between them slow teams down, and how Lakebase finally closes the gap between OLTP applications and OLAP analytics.',
  },
  {
    title:
      'Introducing LTAP (Lake Transactional/Analytical Processing): a new data processing architecture',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=9J2-PovJppA',
    summary:
      'Reynold Xin introduces LTAP, which brings Lakebase and the lakehouse together so operational, analytical, and streaming data share a single governed copy — combining serverless Postgres on open object storage with the lakehouse and removing ETL, replicas, and pipelines.',
  },
  {
    title: 'LTAP: The first Lake Transactional/Analytical Processing architecture — Demo',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=19nQxHcWDg0',
    summary:
      'Holly Smith (Developer Relations, Databricks) demos LTAP unifying OLTP and OLAP on a single copy of data, creating one source of truth for operational, analytical, and streaming workloads without the usual data engineering work.',
  },
  {
    title: 'Lakebase: Building the Operational Foundation for AI Agents',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Jun 2026',
    url: 'https://www.youtube.com/watch?v=2SJkhiNizcI',
    summary:
      'Andre Landgraf and Jason Pohl show how separating storage and compute gives Lakebase instant branching, sub-second creation, and autoscaling — covering branching for safer development, pgvector for agent search, multi-tenant SaaS apps, and how Replit and Superhuman use Lakebase.',
  },
  {
    title: 'Lakebase 101: Serverless PostgreSQL Built for the AI Era on Databricks',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Aug 2026',
    url: 'https://www.youtube.com/watch?v=jlCKbhyWivo',
    summary:
      'An end-to-end tour of the Lakebase architecture: decoupled compute and storage that autoscales in under 500 ms, instant copy-on-write branches, scale-to-zero, sub-second point-in-time recovery, bidirectional lakehouse sync, and Unity Catalog registration for queries that mix OLTP and OLAP data.',
  },
  {
    title: 'Safe AI Agent Development with Lakebase: Database Branching for Non-Destructive Builds',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=vzKTMaJKanQ',
    summary:
      'Anthony Giuliano explains why database incidents dominate agentic-AI failure stories and demonstrates how Lakebase branches — cheap pointers rather than full copies — let AI coding agents work against realistic data without putting production at risk.',
  },
  {
    title: 'Lakebase Architecture Explained: OLTP on Object Storage for Cloud and AI',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=LsiMwjW5aS8',
    summary:
      'A walkthrough of Lakebase internals: how a WAL dispatcher hides object-storage latency, how the page store and buffer pool serve multiple Postgres instances, and how placing all data on object storage enables instant provisioning, copy-on-write branching, autoscaling, and analytics on operational data.',
  },
  {
    title:
      "Lakebase Database Branching in a PCI-DSS Environment: HTEC's G2 Nimbus Case Study",
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=ZZFPmtLVBfU',
    summary:
      'How HTEC used Lakebase branching to accelerate G2 Nimbus, a multi-year migration of a 25-year-old bankruptcy-risk intelligence system under strict PCI DSS network segregation — with branch-per-feature databases, parallel QA environments, and safe hotfixes that never touch live data.',
  },
  {
    title: 'Lakebase Search for AI Agents: Hybrid Vector + BM25 on Postgres at Billion-Row Scale',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=vtGgnrgvurk',
    summary:
      'A deep dive on Lakebase Search: BM25 full-text indexing alongside HNSW and IVF vector indexes, with single-statement SQL that fuses vector rankings, keyword matches, and structured filters. Covers why agent search is an OLTP workload and how IVF indexing on object storage cuts storage 32x versus standard pgvector.',
  },
  {
    title: 'Ship Faster: Dev Workflows with Lakebase Branching',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=H0KhushS_3Y',
    summary:
      'A lightning talk on ending the shared-dev-database bottleneck: spinning up an isolated, zero-copy clone per feature branch, pull request, or developer in seconds, and slotting it into local development, CI pipelines, and staging without maintaining separate database instances.',
  },
  {
    title:
      'Why Vector Stores Are Not Enough: Using Lakebase as a Durable Memory Layer for Autonomous Agents',
    mediaType: 'Video',
    source: 'YouTube',
    date: 'Sep 2026',
    url: 'https://www.youtube.com/watch?v=1mfPqRT5SeE',
    summary:
      'Argues that agents need deterministic, transactional state rather than probabilistic similarity alone, then builds a self-improving “stateful worker” agent on Databricks Apps, Jobs, and Lakebase Autoscaling — with asynchronous “dreaming” distillation jobs that let agents get smarter overnight.',
  },
  {
    title: 'Hafnia modernizes maritime operations with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jan 2026',
    url: 'https://www.databricks.com/customers/hafnia/lakebase',
    summary:
      'One of the world’s largest product and chemical tanker companies built a self-service “data supermarket” on Databricks, with a growing share of its apps powered by Lakebase. Production app delivery dropped from two months to five days for a data team supporting 10 departments, 200+ vessels, and 4,500+ crew.',
  },
  {
    title: 'easyJet: Creating better travel experiences for all',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Feb 2026',
    url: 'https://www.databricks.com/customers/easyjet/lakebase',
    summary:
      'Moving off a decade-old desktop app and one of Europe’s largest SQL Server databases, easyJet modernised revenue management with Lakebase and Databricks Apps — cutting time to launch revenue-management apps from 6–9 months to 3–4, and consolidating 100+ Git repos into two.',
  },
  {
    title: 'DEICHMANN: Operationalizing customer data for omnichannel marketing',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Feb 2026',
    url: 'https://www.databricks.com/customers/deichmann/lakebase',
    summary:
      'Europe’s largest footwear retailer uses Lakebase as a production-ready bridge between its lakehouse analytics and customer engagement, activating governed marketing data — including into SAP Emarsys — for e-commerce teams across 30+ countries while reducing operational overhead.',
  },
  {
    title: 'How Superhuman Replaced Custom Sync Infrastructure with Lakebase and Databricks Apps',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Apr 2026',
    url: 'https://www.databricks.com/customers/superhuman/lakebase',
    summary:
      'By replacing custom Redis and DynamoDB sync infrastructure with Lakebase’s automated sync, Superhuman (Grammarly, Coda, Superhuman Mail) cut ML data-integration projects from about three months to two weeks, moved from quarterly to weekly launches, and reduced on-call load 20x.',
  },
  {
    title: 'How Ibotta eliminated its serving layer and cut latency 10x with Lakebase on Databricks',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Apr 2026',
    url: 'https://www.databricks.com/customers/ibotta/lakebase',
    summary:
      'North America’s largest digital promotions network replaced AWS RDS and always-on SQL warehouse serving with Lakebase, cutting ML serving latency 3–10x and serving compute costs by 90%, with zero outages since migration for apps reaching 200M+ consumers.',
  },
  {
    title:
      'How Afresh Replaced Azure Postgres with Lakebase and Unified Data for 12,500+ Grocery Departments',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/customers/afresh/lakebase',
    summary:
      'Afresh, which powers fresh-food ordering for 12,500+ grocery departments, replaced Azure Postgres with Lakebase to unify operational and analytical data under Unity Catalog — turning two-day ML refresh fixes into a one-line code change and retiring a 10M-row circular sync pipeline.',
  },
  {
    title: 'TBC Bank Operationalizes Trusted Data with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/customers/tbcbank/lakebase',
    summary:
      'The largest banking group in the Caucasus moved off on-premises SQL Server and month-long reporting cycles, deploying Lakebase in a couple of hours and pairing it with Databricks Apps and Genie to power self-service analytics and AI-driven applications.',
  },
  {
    title: 'Zillow Unifies Systems on Databricks and Powers Persistent AI Memory with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/customers/zillow/lakebase',
    summary:
      'Zillow standardized a sprawl of tools onto one governed Databricks ecosystem, using Lakebase to give its agentic AI persistent memory — cutting operational overhead 65% and platform support tickets per active user 44% for a business serving 250M+ monthly users.',
  },
  {
    title:
      'How SEDUC simplified data architecture and reduced infrastructure costs by 100% with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jun 2026',
    url: 'https://www.databricks.com/customers/seduc/lakebase',
    summary:
      'São Paulo’s State Department of Education replaced Apache Cassandra with serverless Lakebase for high-volume attendance and classroom applications, eliminating dedicated 24/7 infrastructure costs while handling up to 22 million records a day.',
  },
  {
    title: 'Independer cuts feature delivery 50% with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/customers/independer/lakebase',
    summary:
      'The Netherlands’ largest independent comparison platform used Lakebase to remove its last-mile export bottleneck from gold tables to production APIs, halving Customer 360 development cycles and unifying data, application, and AI teams for 21M annual visitors.',
  },
  {
    title: 'Lipton eliminated data duplication and cut storage costs 30% with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/customers/lipton/lakebase',
    summary:
      'The world’s largest tea company unified factory-floor operations and analytics on Lakebase so operators can view and correct live production data, cutting storage costs 30% and speeding application changes from weeks to days with branching and familiar SQL/Python tooling.',
  },
  {
    title: 'How DXC Built a GenAI Workforce Agent for 130,000 Consultants Using Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/customers/dxc/lakebase',
    summary:
      'DXC Technology deployed a GenAI competency agent on Databricks and Lakebase that analyzes signals across enterprise systems to give 130,000 consultants in 70+ countries personalized skill recommendations, cutting processing time 94% — from two hours to about seven minutes.',
  },
  {
    title: 'Ubisoft Cuts Time to Insight from Days to Seconds with Genie and Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Jul 2026',
    url: 'https://www.databricks.com/customers/ubisoft/lakebase',
    summary:
      'Replacing an aging Hadoop ecosystem, Ubisoft now moves data from the lake to user-facing apps and game services through Lakebase in seconds rather than 30 minutes to 2 hours, while Genie answers ad hoc playtest questions directly for teams behind franchises like Assassin’s Creed.',
  },
  {
    title: 'How PRADA Group is redefining luxury experiences through real-time insights',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/pradagroup/lakebase',
    summary:
      'PRADA Group built a unified data and AI foundation on Lakebase across Prada, Miu Miu, Church’s, and Versace, cutting infrastructure costs ~50% by retiring always-on cluster serving and dropping API response times from ~2 seconds to 15 milliseconds.',
  },
  {
    title: 'Worldpanel by Numerator Cut Reporting from 12 Days to 1 with Lakebase on Databricks',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/numerator/lakebase',
    summary:
      'By building its Item Picker on Lakebase, Worldpanel by Numerator made 18 billion shopper records navigable in one fast, governed UI for teams across 30+ countries — broadening self-service access and cutting global report delivery by more than 90%.',
  },
  {
    title: 'How CMSPI Delivered $27M in Merchant Savings in Six Months with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/CMSPI/lakebase',
    summary:
      'CMSPI, whose clients include about one in four Global 500 companies, added Lakebase as an operational layer so consultants can test scenarios, save drafts, and refine insights interactively — delivering 80x faster scenario analysis and $27M in incremental merchant savings in six months.',
  },
  {
    title: 'ERGO Hestia implements real-time insurance pricing with Lakebase',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/ergo-hestia/lakebase',
    summary:
      'One of Poland’s largest insurers replaced an external Azure PostgreSQL database with Lakebase and Model Serving endpoints for real-time production pricing over REST APIs — one of Europe’s first Databricks-native real-time serving implementations in financial services.',
  },
  {
    title: 'How Novo Nordisk achieved 30x faster clinical trial data ingestion',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/novo-nordisk/lakebase',
    summary:
      'Novo Nordisk replaced fragmented, self-hosted Postgres silos with an API layer powered by Lakebase, delivering clinical trial data 30x faster with horizontal scale and consistent, auditable data in a regulated environment.',
  },
  {
    title:
      'Customer Zero: How Retool scaled its operational layer with Lakebase and cut costs by 80%',
    mediaType: 'Customer Story',
    source: 'Databricks Customers',
    date: 'Aug 2026',
    url: 'https://www.databricks.com/customers/retool/lakebase',
    summary:
      'As vibe-coded apps multiplied, Retool became Customer Zero for Lakebase, moving its operational layer onto serverless Postgres governed by Unity Catalog. It now runs 1M+ governed databases, provisions new ones in milliseconds, and cut annual operating costs 80%.',
  },
];
