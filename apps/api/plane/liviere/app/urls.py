# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Mounted under /api/ by plane/app/urls/__init__.py (session authentication).

from django.urls import path

from .views import PageApiBlockEndpoint

urlpatterns = [
    path(
        "workspaces/<str:slug>/projects/<uuid:project_id>/pages/<uuid:page_id>/liviere/api-block/",
        PageApiBlockEndpoint.as_view(http_method_names=["post", "delete"]),
        name="liviere-page-api-block",
    ),
]
