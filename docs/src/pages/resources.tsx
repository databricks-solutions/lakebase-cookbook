import React from "react";
import Layout from "@theme/Layout";

interface Resource {
  title: string;
  type: string;
  category: string;
  url: string;
  summary: string;
}

const RESOURCES: Resource[] = [
  {
    title: "Lakebase product overview",
    type: "Documentation",
    category: "Overview",
    url: "https://www.databricks.com/product/lakebase",
    summary:
      "Official announcement and product page for Databricks Lakebase, the managed Postgres-compatible OLTP database.",
  },
  {
    title: "Lakebase / OLTP documentation",
    type: "Documentation",
    category: "Overview",
    url: "https://docs.databricks.com/aws/en/oltp/",
    summary:
      "Official documentation covering Lakebase projects, branches, Postgres roles, synced tables, and the Data API.",
  },
  {
    title: "Postgres roles in Lakebase",
    type: "Documentation",
    category: "Security",
    url: "https://docs.databricks.com/aws/en/oltp/projects/postgres-roles",
    summary:
      "How to create and manage Postgres roles for users and service principals against a Lakebase project.",
  },
  {
    title: "Genie Caching example",
    type: "Code sample",
    category: "Apps",
    url: "https://github.com/databricks-solutions/lakebase-cookbook/tree/main/genie_caching",
    summary:
      "A Databricks App that fronts Genie with a Lakebase (pgvector) semantic query cache, deployable via Asset Bundles.",
  },
];

function ResourcesPage() {
  return (
    <Layout title="Resources">
      <div className="px-4 py-8">
        <div className="container mx-auto">
          <h1 className="mb-4 text-4xl font-bold">Lakebase Resources</h1>
          <p className="mb-8">
            A collection of resources for building on Databricks Lakebase.
            Submit a resource by{" "}
            <a
              href="https://github.com/databricks-solutions/lakebase-cookbook/pulls"
              target="_blank"
              rel="noopener noreferrer"
              className="hover:underline"
            >
              raising a PR
            </a>
            .
          </p>
          <main className="w-full">
            <div className="grid grid-cols-1 gap-8 md:grid-cols-2">
              {RESOURCES.map((resource, index) => (
                <div
                  key={index}
                  className="border bg-[#F9F7F4] p-6 shadow-lg transition-shadow hover:shadow-xl dark:border-gray-700 dark:bg-[#242526]"
                >
                  <h2 className="mb-2 text-xl font-bold">
                    <a
                      href={resource.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-lava-600 hover:underline dark:text-lava-500"
                    >
                      {resource.title}
                    </a>
                  </h2>
                  <p className="text-sm text-gray-700 dark:text-gray-400">
                    {resource.summary}
                  </p>
                  <div className="mt-4 text-sm font-medium">
                    <span className="mr-2 mb-2 inline-block border border-lava-600 bg-transparent px-3 py-1 text-sm font-semibold text-lava-600 dark:border-lava-500 dark:text-lava-500">
                      {resource.type}
                    </span>
                    <span className="mr-2 mb-2 inline-block border border-[#1B3139] bg-transparent px-3 py-1 text-sm font-semibold text-[#1B3139] dark:border-gray-500 dark:text-gray-400">
                      {resource.category}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </main>
        </div>
      </div>
    </Layout>
  );
}

export default ResourcesPage;
