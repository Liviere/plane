# Copyright (c) 2023-present Plane Software, Inc. and contributors
# SPDX-License-Identifier: AGPL-3.0-only
# See the LICENSE file for details.

# Project activity heatmap in the public API (/api/v1, X-Api-Key). Read only; the settings change in the
# app. See plane/liviere/activity.

# Module imports
from plane.api.views.base import BaseAPIView
from plane.app.permissions import ROLE, allow_permission
from plane.liviere.activity.endpoints import ActivityHandlers


class ProjectActivityHeatmapAPIEndpoint(ActivityHandlers, BaseAPIView):
    use_read_replica = True

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        return self.get_heatmap(request, project_id)


class ProjectActivityEventsAPIEndpoint(ActivityHandlers, BaseAPIView):
    use_read_replica = True

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        return self.get_events(request, project_id)


class ProjectActivitySettingsAPIEndpoint(ActivityHandlers, BaseAPIView):
    use_read_replica = True

    @allow_permission([ROLE.ADMIN, ROLE.MEMBER])
    def get(self, request, slug, project_id):
        return self.get_settings(request, project_id)
