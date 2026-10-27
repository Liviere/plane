# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Handlers shared by the app endpoints (session, plane/liviere/app) and the public API (API key,
# plane/liviere/api). Reading needs a project admin or member (guests may not see every work item the
# events point to); changing the settings needs a project admin.

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.liviere.activity.kinds import CATALOG, parse_kinds
from plane.liviere.activity.queries import (
    InvalidParams,
    event_range,
    filtered_events,
    heatmap,
    parse_params,
    project_settings,
    serialize_events,
)
from plane.liviere.models import ProjectActivitySettings


def bad_request(error):
    return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)


def settings_payload(project_settings_obj):
    return {
        "enabled": project_settings_obj.enabled,
        "kinds": project_settings_obj.kinds,
        "catalog": [
            {"group": group, "kinds": [{"key": key, "default": default} for key, default in kinds]}
            for group, kinds in CATALOG
        ],
    }


class ActivityHandlers:
    """Mixed into BaseAPIView subclasses; the subclass adds permissions and authentication."""

    def get_heatmap(self, request, project_id):
        try:
            query = parse_params(request, project_id)
        except InvalidParams as e:
            return bad_request(e)
        return Response(heatmap(project_id, query), status=status.HTTP_200_OK)

    def get_events(self, request, project_id):
        try:
            query = parse_params(request, project_id)
            since, until = event_range(request, query)
        except InvalidParams as e:
            return bad_request(e)
        events = filtered_events(project_id, query, since, until).select_related("actor").order_by("-occurred_at")
        return self.paginate(
            request=request,
            queryset=events,
            on_results=serialize_events,
            default_per_page=100,
            max_per_page=1000,
        )

    def get_settings(self, request, project_id):
        return Response(settings_payload(project_settings(project_id)), status=status.HTTP_200_OK)

    def patch_settings(self, request, project_id):
        data = request.data
        changes = {}
        if "enabled" in data:
            if not isinstance(data["enabled"], bool):
                return bad_request("'enabled' must be true or false")
            changes["enabled"] = data["enabled"]
        if "kinds" in data:
            if not isinstance(data["kinds"], list):
                return bad_request("'kinds' must be a list of activity kinds")
            try:
                changes["kinds"] = parse_kinds(data["kinds"])
            except ValueError as e:
                return bad_request(e)
        if not changes:
            return bad_request("Nothing to change: send 'enabled' and/or 'kinds'")

        obj, _ = ProjectActivitySettings.objects.update_or_create(
            project_id=project_id, defaults={**changes, "updated_by": request.user}
        )
        return Response(settings_payload(obj), status=status.HTTP_200_OK)
