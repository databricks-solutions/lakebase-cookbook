import React from "react";
import Layout from "@theme/Layout";

type MediaType = "Video" | "Blog" | "Announcement";

interface ArchiveEntry {
  title: string;
  mediaType: MediaType;
  source: string;
  date: string;
  url: string;
  summary: string;
}

// To add an entry, append to this list and open a pull request.
const ARCHIVE: ArchiveEntry[] = [
  {
    title: "Data + AI Summit 2026 Keynote — Day 1",
    mediaType: "Video",
    source: "YouTube",
    date: "Jun 2026",
    url: "https://www.youtube.com/watch?v=Qux8E-L1mk8",
    summary:
      "The Data + AI Summit day-one keynote, where Databricks leaders presented the latest Lakebase capabilities, including cross-region and cross-cloud disaster recovery, alongside live product demos.",
  },
  {
    title: "A New Era of Databases: Lakebase",
    mediaType: "Blog",
    source: "Databricks Blog",
    date: "Jun 2025",
    url: "https://www.databricks.com/blog/what-is-a-lakebase",
    summary:
      "The foundational explainer for Lakebase: what a lakebase is, why separating compute from storage on open formats matters, and how it unifies operational and analytical data.",
  },
  {
    title:
      "Databricks Launches Lakebase: a New Class of Operational Database for AI Apps and Agents",
    mediaType: "Announcement",
    source: "Databricks Newsroom",
    date: "Jun 2025",
    url: "https://www.databricks.com/company/newsroom/press-releases/databricks-launches-lakebase-new-class-operational-database-ai-apps",
    summary:
      "The official launch announcement detailing Lakebase's branching, autoscaling, low-latency high-concurrency performance, and synchronization to and from the lakehouse.",
  },
  {
    title: "Announcing Lakebase Public Preview",
    mediaType: "Blog",
    source: "Databricks Blog",
    date: "Jun 2025",
    url: "https://www.databricks.com/blog/announcing-lakebase-public-preview",
    summary:
      "The public preview announcement, walking through how to get started with Lakebase and the core developer experience.",
  },
  {
    title: "Databricks Lakebase is now Generally Available",
    mediaType: "Blog",
    source: "Databricks Blog",
    date: "2025",
    url: "https://www.databricks.com/blog/databricks-lakebase-generally-available",
    summary:
      "The general availability milestone for Lakebase, covering production readiness and the capabilities available to all customers.",
  },
  {
    title: "How the Lakebase Architecture Stays Resilient to Cloud Failures",
    mediaType: "Blog",
    source: "Databricks Blog",
    date: "2025",
    url: "https://www.databricks.com/blog/how-lakebase-architecture-stays-resilient-cloud-failures",
    summary:
      "A deep dive into the resilience of the Lakebase architecture and how it maintains availability and durability through cloud failures.",
  },
  {
    title: "Announcing Databricks Lakebase Launch Partners",
    mediaType: "Blog",
    source: "Databricks Blog",
    date: "Jun 2025",
    url: "https://www.databricks.com/blog/announcing-databricks-lakebase-launch-partners",
    summary:
      "An overview of the ecosystem of launch partners building on and integrating with Lakebase.",
  },
  {
    title:
      "Databricks Launches LTAP: The First Lake Transactional/Analytical Processing Architecture",
    mediaType: "Announcement",
    source: "Databricks Newsroom",
    date: "Jun 2026",
    url: "https://www.databricks.com/company/newsroom/press-releases/databricks-launches-ltap-first-lake-transactionalanalytical",
    summary:
      "The announcement of LTAP, unifying transactions, analytics, streaming, and operational data on a single governed copy of storage — the architecture Lakebase builds on.",
  },
];

const tagClass: Record<MediaType, string> = {
  Video:
    "border-lava-600 text-lava-600 dark:border-lava-500 dark:text-lava-500",
  Blog: "border-[#1B3139] text-[#1B3139] dark:border-gray-500 dark:text-gray-400",
  Announcement:
    "border-[#1B3139] text-[#1B3139] dark:border-gray-500 dark:text-gray-400",
};

function ArchivesPage() {
  return (
    <Layout
      title="Archives"
      description="A curated archive of videos, blogs, and announcements highlighting the success of Databricks Lakebase."
    >
      <div className="px-4 py-10 sm:px-6 sm:py-14">
        <div className="container mx-auto max-w-6xl">
          <h1 className="mb-4 text-4xl font-bold sm:text-5xl">Archives</h1>
          <p className="mb-10 max-w-3xl text-gray-700 dark:text-gray-300">
            A curated archive of videos, blogs, and announcements highlighting
            the success of Databricks Lakebase. To add an entry, open a pull
            request against{" "}
            <a
              href="https://github.com/databricks-solutions/lakebase-cookbook/pulls"
              target="_blank"
              rel="noopener noreferrer"
              className="text-lava-600 hover:underline dark:text-lava-500"
            >
              the repository
            </a>
            .
          </p>

          <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
            {ARCHIVE.map((entry) => (
              <div
                key={entry.url}
                className="flex flex-col border bg-[#F9F7F4] p-6 shadow-lg transition-shadow hover:shadow-xl dark:border-gray-700 dark:bg-[#242526]"
              >
                <h2 className="mb-2 text-xl font-bold">
                  <a
                    href={entry.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-lava-600 hover:underline dark:text-lava-500"
                  >
                    {entry.title}
                  </a>
                </h2>
                <div className="mb-3 text-sm text-gray-500 dark:text-gray-400">
                  {entry.source} &middot; {entry.date}
                </div>
                <p className="flex-1 text-sm leading-relaxed text-gray-700 dark:text-gray-300">
                  {entry.summary}
                </p>
                <div className="mt-4 text-sm font-medium">
                  <span
                    className={`mr-2 mb-2 inline-block border bg-transparent px-3 py-1 text-sm font-semibold ${tagClass[entry.mediaType]}`}
                  >
                    {entry.mediaType}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Layout>
  );
}

export default ArchivesPage;
