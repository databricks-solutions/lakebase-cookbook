"""Generate LangGraph pipeline diagrams from the compiled graph.

Usage:
    # Print Mermaid syntax to stdout
    python scripts/generate_graph_diagram.py

    # Save as Mermaid file
    python scripts/generate_graph_diagram.py --output pipeline.mmd

    # Save as PNG (requires: pip install mermaid-py  or  npm install -g @mermaid-js/mermaid-cli)
    python scripts/generate_graph_diagram.py --png pipeline_langgraph.png

Requires a working Databricks environment (or mock config) since the graph
module imports backend.config at load time.
"""

import argparse
import os
import sys

# Running this file directly puts scripts/ on sys.path, not the project root, so
# `import backend...` fails with ModuleNotFoundError regardless of the working
# directory. Add the project root explicitly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Generate LangGraph pipeline diagram")
    parser.add_argument("--output", "-o", help="Save Mermaid to file (default: stdout)")
    parser.add_argument("--png", help="Render to PNG via draw_mermaid_png()")
    args = parser.parse_args()

    from backend.services.graph import build_pipeline_graph

    graph = build_pipeline_graph()
    drawable = graph.get_graph()

    mermaid_src = drawable.draw_mermaid()

    if args.png:
        try:
            png_bytes = drawable.draw_mermaid_png()
            with open(args.png, "wb") as f:
                f.write(png_bytes)
            print(f"PNG saved to {args.png}")
        except Exception as e:
            print(f"PNG generation failed ({e}). Falling back to Mermaid output.", file=sys.stderr)
            print(mermaid_src)
        return

    if args.output:
        with open(args.output, "w") as f:
            f.write(mermaid_src)
        print(f"Mermaid saved to {args.output}")
    else:
        print(mermaid_src)


if __name__ == "__main__":
    main()
