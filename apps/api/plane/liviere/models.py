# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Models of the Liviere/plane fork. They live in their own Django app (label "liviere") with its own
# migrations, so they never clash with upstream migrations in plane/db.

# Django imports
from django.conf import settings
from django.db import models

# Module imports
from plane.liviere.activity.kinds import DEFAULT_KINDS


def default_activity_kinds():
    return list(DEFAULT_KINDS)


class ActivityEvent(models.Model):
    """One action in a project, counted by the activity heatmap (plane/liviere/activity)."""

    SOURCE_ISSUE_ACTIVITY = "issue_activity"
    SOURCE_PAGE = "page"
    SOURCE_CYCLE = "cycle"
    SOURCE_MODULE = "module"
    SOURCE_VIEW = "view"

    id = models.BigAutoField(primary_key=True)
    workspace = models.ForeignKey("db.Workspace", on_delete=models.CASCADE, related_name="+")
    project = models.ForeignKey("db.Project", on_delete=models.CASCADE, related_name="+")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    occurred_at = models.DateTimeField()
    kind = models.CharField(max_length=40)
    source = models.CharField(max_length=20)
    # Id of the IssueActivity row the event was copied from; makes the copy idempotent
    source_id = models.UUIDField(null=True)
    # The object acted on (no foreign keys: events outlive deleted objects)
    issue_id = models.UUIDField(null=True)
    page_id = models.UUIDField(null=True)
    object_id = models.UUIDField(null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "liviere_activity_events"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_id"],
                condition=models.Q(source_id__isnull=False),
                name="liviere_activity_event_unique_source",
            )
        ]
        indexes = [
            models.Index(fields=["project", "occurred_at"], name="liviere_act_project_time"),
            models.Index(fields=["project", "actor", "occurred_at"], name="liviere_act_project_actor"),
        ]


class ProjectActivitySettings(models.Model):
    """Per-project switch of the "Activity" feature and the actions it counts."""

    project = models.OneToOneField("db.Project", on_delete=models.CASCADE, related_name="+", primary_key=True)
    enabled = models.BooleanField(default=False)
    kinds = models.JSONField(default=default_activity_kinds)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        db_table = "liviere_project_activity_settings"
