import type { ReactNode } from "react";
import Link from "@docusaurus/Link";
import useDocusaurusContext from "@docusaurus/useDocusaurusContext";
import Layout from "@theme/Layout";
import Heading from "@theme/Heading";
import HeaderAnimation from "../components/HeaderAnimation";
import { useColorMode } from "@docusaurus/theme-common";

const primaryButton =
  "w-full border-2 border-lava-700 bg-lava-700 px-8 py-2.5 align-middle font-semibold text-white hover:cursor-pointer hover:border-lava-800 hover:bg-lava-800 hover:underline sm:text-lg";

const secondaryButton =
  "w-full border-2 border-gray-800 bg-transparent px-8 py-2.5 align-middle font-semibold text-gray-800 hover:cursor-pointer hover:underline sm:text-lg dark:border-white dark:text-white";

function HomepageHeader() {
  const { siteConfig } = useDocusaurusContext();
  const { colorMode } = useColorMode();
  const isDarkTheme = colorMode === "dark";

  return (
    <header className="relative w-full overflow-hidden">
      <HeaderAnimation isDarkMode={isDarkTheme} />
      <div className="relative z-10 mx-auto flex min-h-[70vh] w-full max-w-5xl flex-col items-center justify-center gap-5 px-4 py-16 text-center sm:min-h-[80vh] sm:py-24">
        <Heading
          as="h1"
          className="text-4xl font-bold text-gray-800 sm:text-6xl md:text-7xl dark:text-white"
        >
          {siteConfig.title}
        </Heading>
        <p className="max-w-3xl text-lg text-gray-800 sm:text-2xl md:text-3xl md:leading-10 dark:text-white">
          {siteConfig.tagline}
        </p>

        {/* Primary actions */}
        <div className="flex w-full max-w-md flex-col items-stretch justify-center gap-4 sm:w-auto sm:max-w-none sm:flex-row">
          <Link to="/docs/category/examples" className="w-full sm:w-auto">
            <button className={primaryButton}>Browse Examples</button>
          </Link>
          <Link to="/docs/examples/genie-caching" className="w-full sm:w-auto">
            <button className={primaryButton}>Genie Caching</button>
          </Link>
          <Link to="/docs/intro" className="w-full sm:w-auto">
            <button className={secondaryButton}>Learn more</button>
          </Link>
        </div>

        {/* Secondary actions: same size as the primary row, sit just below it */}
        <div className="flex w-full max-w-md flex-col items-stretch justify-center gap-4 sm:w-auto sm:flex-row">
          <Link to="/why-lakebase" className="w-full sm:w-auto">
            <button className={primaryButton}>Why Lakebase</button>
          </Link>
          <Link to="/archives" className="w-full sm:w-auto">
            <button className={primaryButton}>Archives</button>
          </Link>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const { siteConfig } = useDocusaurusContext();
  return (
    <Layout description={`${siteConfig.tagline}`}>
      <HomepageHeader />
    </Layout>
  );
}
