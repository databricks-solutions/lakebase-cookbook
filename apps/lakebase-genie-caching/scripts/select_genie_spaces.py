#!/usr/bin/env python3
"""Select Genie Spaces and print the DAB --var argument.

This helper is intentionally lightweight: it lists spaces in the target
workspace, lets a deployer choose by number or ID, and prints the bundle flag
needed for environment-specific `genie_space_ids`.
"""

from __future__ import annotations

import argparse
from typing import Any

from databricks.sdk import WorkspaceClient


def parse_selection(selection: str, spaces: list[dict[str, Any]]) -> list[str]:
    """Parse comma-separated 1-based indices and/or literal Genie Space IDs."""
    selected: list[str] = []
    by_index = {str(i + 1): space["space_id"] for i, space in enumerate(spaces)}

    for raw_part in selection.split(","):
        part = raw_part.strip()
        if not part:
            continue
        selected.append(by_index.get(part, part))

    return selected


def render_var_argument(space_ids: list[str]) -> str:
    """Render the Databricks bundle variable flag for selected Genie Spaces."""
    return f"--var='genie_space_ids={','.join(space_ids)}'"


def list_genie_spaces(profile: str | None = None) -> list[dict[str, str]]:
    """List Genie Spaces available to the current user/profile.

    ``genie.list_spaces()`` returns a ``GenieListSpacesResponse``, not an
    iterable of spaces -- iterating it directly raised
    ``TypeError: 'GenieListSpacesResponse' object is not iterable``, so this
    script failed for everyone. The response is also paginated, and a workspace
    with more spaces than one page would otherwise silently show a truncated list.
    """
    w = WorkspaceClient(profile=profile) if profile else WorkspaceClient()
    spaces: list[dict[str, str]] = []
    page_token: str | None = None

    while True:
        response = w.genie.list_spaces(page_token=page_token) if page_token else w.genie.list_spaces()
        for space in response.spaces or []:
            spaces.append(
                {
                    "space_id": space.space_id,
                    "title": getattr(space, "title", "") or space.space_id,
                }
            )
        page_token = getattr(response, "next_page_token", None)
        if not page_token:
            break

    return spaces


def main() -> None:
    parser = argparse.ArgumentParser(description="Select Genie Spaces for DAB deployment")
    parser.add_argument("--profile", help="Databricks CLI profile")
    parser.add_argument("--selection", help="Comma-separated indices or Genie Space IDs")
    args = parser.parse_args()

    spaces = list_genie_spaces(args.profile)
    if not spaces:
        raise SystemExit("No Genie Spaces found for the selected workspace/profile.")

    for i, space in enumerate(spaces, start=1):
        print(f"{i}. {space['title']} ({space['space_id']})")

    selection = args.selection or input("Select Genie Spaces by number or ID (comma-separated): ")
    selected = parse_selection(selection, spaces)

    print(render_var_argument(selected))


if __name__ == "__main__":
    main()
