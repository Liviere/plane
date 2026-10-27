/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Liviere/plane fork: data hooks of the project activity heatmap.

import { useCallback } from "react";
import useSWR, { mutate } from "swr";
import { EUserPermissions } from "@plane/constants";
import type { TNavigationItem } from "@/components/navigation/tab-navigation-root";
import { projectActivityService } from "./activity.service";
import { ActivityIcon } from "./activity-icon";
import type { TActivityQuery } from "./types";

export const ACTIVITY_NAVIGATION_KEY = "liviere_activity";

export const enabledProjectsKey = (workspaceSlug: string) => `LIVIERE_ACTIVITY_ENABLED_PROJECTS_${workspaceSlug}`;
export const activitySettingsKey = (projectId: string) => `LIVIERE_ACTIVITY_SETTINGS_${projectId}`;

export const useActivityEnabledProjects = (workspaceSlug: string | undefined) =>
  useSWR(
    workspaceSlug ? enabledProjectsKey(workspaceSlug) : null,
    workspaceSlug ? () => projectActivityService.getEnabledProjectIds(workspaceSlug) : null,
    { revalidateOnFocus: false }
  );

/** "Activity" item of the project navigation (sidebar and tabs), shown where the feature is enabled. */
export const useActivityNavigationItems = (workspaceSlug: string | undefined) => {
  const { data: enabledProjectIds } = useActivityEnabledProjects(workspaceSlug);
  return useCallback(
    (slug: string, projectId: string): TNavigationItem[] => [
      {
        i18n_key: "liviere.activity.title",
        key: ACTIVITY_NAVIGATION_KEY,
        name: "Activity",
        href: `/${slug}/projects/${projectId}/activity`,
        icon: ActivityIcon,
        access: [EUserPermissions.ADMIN, EUserPermissions.MEMBER],
        shouldRender: !!enabledProjectIds?.includes(projectId),
        sortOrder: 7,
      },
    ],
    [enabledProjectIds]
  );
};

export const useActivitySettings = (workspaceSlug: string | undefined, projectId: string | undefined) =>
  useSWR(
    workspaceSlug && projectId ? activitySettingsKey(projectId) : null,
    workspaceSlug && projectId ? () => projectActivityService.getSettings(workspaceSlug, projectId) : null,
    { revalidateOnFocus: false }
  );

export const useActivityHeatmap = (workspaceSlug: string, projectId: string, query: TActivityQuery) =>
  useSWR(
    `LIVIERE_ACTIVITY_HEATMAP_${projectId}_${query.from}_${query.to}_${query.tz}_${query.actor ?? ""}`,
    () => projectActivityService.getHeatmap(workspaceSlug, projectId, query),
    { refreshInterval: 60_000, keepPreviousData: true }
  );

/** Reloads the heatmap and the event lists of a project, e.g. after a log entry changed. */
export const refreshProjectActivity = (projectId: string) =>
  mutate(
    (key) =>
      typeof key === "string" &&
      (key.startsWith(`LIVIERE_ACTIVITY_HEATMAP_${projectId}_`) ||
        key.startsWith(`LIVIERE_ACTIVITY_EVENTS_${projectId}_`))
  );
