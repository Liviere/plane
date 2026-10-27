# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Handlers shared by the app endpoints (session, plane/liviere/app) and the public API (API key,
# plane/liviere/api). Reading needs a project admin or member (guests may not see every work item the
# events point to); changing the settings needs a project admin. Log entries are written by admins and
# members, and changed or deleted by their author or a project admin.

# Python imports
from zoneinfo import ZoneInfo

# Django imports
from django.utils import timezone

# Third party imports
from rest_framework import status
from rest_framework.response import Response

# Module imports
from plane.liviere.activity.kinds import CATALOG, LOG_ENTRY, parse_kinds
from plane.liviere.activity.logs import InvalidLog, is_project_admin, log_changes
from plane.liviere.activity.queries import (
    InvalidParams,
    event_range,
    filtered_events,
    heatmap,
    parse_params,
    project_settings,
    serialize_events,
)
from plane.db.models import Project
from plane.liviere.models import ActivityEvent, ProjectActivitySettings


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

    def get_events(self, request, project_id, kinds=None):
        try:
            query = parse_params(request, project_id)
            since, until = event_range(request, query)
        except InvalidParams as e:
            return bad_request(e)
        if kinds is not None:
            query["kinds"] = kinds
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

    # Log entries

    def _log(self, project_id, log_id):
        return (
            ActivityEvent.objects.filter(id=log_id, project_id=project_id, source=ActivityEvent.SOURCE_LOG)
            .select_related("actor")
            .first()
        )

    def list_logs(self, request, project_id):
        # Entries are listed whatever the project settings count
        return self.get_events(request, project_id, kinds=[LOG_ENTRY])

    def create_log(self, request, slug, project_id):
        project = Project.objects.get(pk=project_id)
        try:
            changes = log_changes(request.data, project, ZoneInfo(project.timezone or "UTC"))
        except InvalidLog as e:
            return bad_request(e)
        entry = ActivityEvent.objects.create(
            workspace_id=project.workspace_id,
            project_id=project_id,
            actor=request.user,
            kind=LOG_ENTRY,
            source=ActivityEvent.SOURCE_LOG,
            **changes,
        )
        # Times as stored (UTC), like every other event
        entry.refresh_from_db()
        return Response(serialize_events([entry])[0], status=status.HTTP_201_CREATED)

    def get_log(self, request, project_id, log_id):
        entry = self._log(project_id, log_id)
        if entry is None:
            return Response({"error": "Log entry not found"}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_events([entry])[0], status=status.HTTP_200_OK)

    def _check_author(self, request, slug, project_id, entry):
        if entry.actor_id == request.user.id or is_project_admin(request.user, slug, project_id):
            return None
        return Response(
            {"error": "Only the author or a project admin can change this entry"}, status=status.HTTP_403_FORBIDDEN
        )

    def patch_log(self, request, slug, project_id, log_id):
        entry = self._log(project_id, log_id)
        if entry is None:
            return Response({"error": "Log entry not found"}, status=status.HTTP_404_NOT_FOUND)
        denied = self._check_author(request, slug, project_id, entry)
        if denied:
            return denied
        project = Project.objects.get(pk=project_id)
        try:
            changes = log_changes(request.data, project, ZoneInfo(project.timezone or "UTC"), current=entry)
        except InvalidLog as e:
            return bad_request(e)
        for field, value in changes.items():
            setattr(entry, field, value)
        entry.updated_at = timezone.now()
        entry.save(update_fields=[*changes, "updated_at"])
        entry.refresh_from_db()
        return Response(serialize_events([entry])[0], status=status.HTTP_200_OK)

    def delete_log(self, request, slug, project_id, log_id):
        entry = self._log(project_id, log_id)
        if entry is None:
            return Response({"error": "Log entry not found"}, status=status.HTTP_404_NOT_FOUND)
        denied = self._check_author(request, slug, project_id, entry)
        if denied:
            return denied
        entry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
