#!/usr/bin/env python3
# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

"""
Compatibility check of the project pages API against plane-sdk 0.3.1 (used by
plane-mcp-server 0.3.3). Runs outside Django, against a running instance:

    pip install plane-sdk==0.3.1
    PLANE_BASE_URL=http://localhost:8090 PLANE_API_KEY=... PLANE_WORKSPACE_SLUG=... \
    PLANE_PROJECT_ID=... python sdk_pages_smoke.py

Sequence: list -> create -> retrieve -> update -> [editor check] -> archive ->
unarchive -> archive -> delete -> retrieve (expects 404).

The editor check is optional: if SMOKE_EDITOR_CHECK is set, it is run as a shell
command with PAGE_ID and EXPECTED_TEXT in the environment and must exit with 0
(for example a headless browser that opens the page and reads the editor).
Never put keys in this file; everything comes from the environment.
"""

import os
import subprocess
import sys
import uuid

from plane import PlaneClient
from plane.errors.errors import HttpError
from plane.models.pages import CreatePage, UpdatePage
from plane.models.query_params import PaginatedQueryParams


def step(name, func):
    try:
        result = func()
    except HttpError as e:
        print(f"FAIL {name}: HTTP {e.status_code} {e.response}")
        sys.exit(1)
    print(f"OK   {name}")
    return result


def main():
    client = PlaneClient(base_url=os.environ["PLANE_BASE_URL"], api_key=os.environ["PLANE_API_KEY"])
    slug = os.environ["PLANE_WORKSPACE_SLUG"]
    project_id = os.environ["PLANE_PROJECT_ID"]
    pages = client.pages
    marker = uuid.uuid4().hex[:8]

    listed = step(
        "list",
        lambda: pages.list_project_pages(slug, project_id, params=PaginatedQueryParams(per_page=20)),
    )
    print(f"     total_count={listed.total_count} results={len(listed.results)}")

    created = step(
        "create",
        lambda: pages.create_project_page(
            slug,
            project_id,
            data=CreatePage(name=f"SDK smoke {marker}", description_html=f"<p>Created by SDK {marker}</p>"),
        ),
    )
    page_id = created.id
    print(f"     id={page_id} owned_by={created.owned_by} projects={created.projects}")

    retrieved = step("retrieve", lambda: pages.retrieve_project_page(slug, project_id, page_id))
    assert retrieved.description_html == f"<p>Created by SDK {marker}</p>", retrieved.description_html

    new_text = f"Updated by SDK {marker}"
    updated = step(
        "update (PUT)",
        lambda: pages.update_project_page(
            slug,
            project_id,
            page_id,
            data=UpdatePage(name=f"SDK smoke {marker} (updated)", description_html=f"<p>{new_text}</p>"),
        ),
    )
    assert updated.description_html == f"<p>{new_text}</p>", updated.description_html

    editor_check = os.environ.get("SMOKE_EDITOR_CHECK")
    if editor_check:
        env = {**os.environ, "PAGE_ID": str(page_id), "EXPECTED_TEXT": new_text}
        result = subprocess.run(editor_check, shell=True, env=env)
        if result.returncode != 0:
            print(f"FAIL editor check (exit {result.returncode})")
            sys.exit(1)
        print("OK   editor shows the content written through the API")
    else:
        print("SKIP editor check (SMOKE_EDITOR_CHECK not set)")

    step("archive", lambda: pages.archive_project_page(slug, project_id, page_id))
    archived = pages.retrieve_project_page(slug, project_id, page_id)
    assert archived.archived_at, "archived_at not set after archive"
    step("unarchive", lambda: pages.unarchive_project_page(slug, project_id, page_id))
    assert pages.retrieve_project_page(slug, project_id, page_id).archived_at is None
    step("archive again", lambda: pages.archive_project_page(slug, project_id, page_id))
    step("delete", lambda: pages.delete_project_page(slug, project_id, page_id))

    try:
        pages.retrieve_project_page(slug, project_id, page_id)
    except HttpError as e:
        if e.status_code in (403, 404):
            print(f"OK   retrieve after delete -> HTTP {e.status_code}")
            return
        raise
    print("FAIL page still retrievable after delete")
    sys.exit(1)


if __name__ == "__main__":
    main()
