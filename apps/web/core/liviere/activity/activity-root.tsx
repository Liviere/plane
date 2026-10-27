/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Liviere/plane fork: the "Activity" page of a project. Rows are days (newest on top), columns are the
// 96 quarters of the day; the colour says how many actions happened in that quarter. Admins and members
// add log entries here (what they did, from when to when); agents do it through the API.

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { Plus } from "lucide-react";
import { EUserPermissions, EUserPermissionsLevel } from "@plane/constants";
import { useTranslation } from "@plane/i18n";
import { Button } from "@plane/propel/button";
import { TOAST_TYPE, setToast } from "@plane/propel/toast";
import { AlertModalCore, Loader } from "@plane/ui";
import { cn } from "@plane/utils";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { useUser, useUserPermissions } from "@/hooks/store/user";
import { projectActivityService } from "./activity.service";
import { ActivityEventList } from "./activity-events";
import { ActivityGrid } from "./activity-grid";
import { ActivityLogModal } from "./activity-log-modal";
import { shiftDate, todayIn } from "./grid";
import type { TActivityEvent } from "./types";
import { refreshProjectActivity, useActivityHeatmap } from "./use-activity";

const RANGES = [7, 30, 90];

type Props = {
  workspaceSlug: string;
  projectId: string;
};

export type TSelectedBucket = { date: string; slot: number };

export const ProjectActivityRoot = observer(function ProjectActivityRoot(props: Props) {
  const { workspaceSlug, projectId } = props;
  const { t, currentLocale } = useTranslation();
  // The viewer's clock: quarters are shown in the time zone of the browser
  const timeZone = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC", []);
  const [days, setDays] = useState(30);
  const [actor, setActor] = useState<string | null>(null);
  const [selected, setSelected] = useState<TSelectedBucket | null>(null);
  // Log entry dialog: null closed, {} new entry, {entry} change
  const [logDialog, setLogDialog] = useState<{ entry?: TActivityEvent } | null>(null);
  const [deleting, setDeleting] = useState<TActivityEvent | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const { data: currentUser } = useUser();
  const { allowPermissions } = useUserPermissions();
  const isAdmin = allowPermissions([EUserPermissions.ADMIN], EUserPermissionsLevel.PROJECT, workspaceSlug, projectId);
  const canChange = (event: TActivityEvent) => isAdmin || (!!currentUser && event.actor?.id === currentUser.id);

  const deleteEntry = async () => {
    if (!deleting) return;
    setIsDeleting(true);
    try {
      await projectActivityService.deleteLog(workspaceSlug, projectId, deleting.id);
      await refreshProjectActivity(projectId);
      setDeleting(null);
    } catch {
      setToast({ type: TOAST_TYPE.ERROR, title: t("error"), message: t("liviere.activity.log.delete_error") });
    } finally {
      setIsDeleting(false);
    }
  };

  const to = todayIn(timeZone);
  const query = { from: shiftDate(to, -(days - 1)), to, tz: timeZone, actor };
  const { data: heatmap, error, isLoading } = useActivityHeatmap(workspaceSlug, projectId, query);

  return (
    <div className="flex h-full w-full flex-col gap-5 overflow-y-auto px-6 py-5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex overflow-hidden rounded-md border border-subtle">
          {RANGES.map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => {
                setDays(range);
                setSelected(null);
              }}
              className={cn(
                "px-3 py-1 text-13 text-secondary hover:bg-layer-transparent-hover",
                days === range && "bg-layer-transparent-selected font-medium text-primary"
              )}
            >
              {t("liviere.activity.range_days", { days: range })}
            </button>
          ))}
        </div>
        <MemberDropdown
          projectId={projectId}
          value={actor}
          multiple={false}
          onChange={(value) => {
            setActor(value === actor ? null : value);
            setSelected(null);
          }}
          buttonVariant="border-with-text"
          placeholder={t("liviere.activity.all_members")}
          showUserDetails
        />
        {actor && (
          <button
            type="button"
            className="text-13 text-tertiary underline-offset-2 hover:underline"
            onClick={() => {
              setActor(null);
              setSelected(null);
            }}
          >
            {t("liviere.activity.all_members")}
          </button>
        )}
        <Button
          variant="secondary"
          size="sm"
          prependIcon={<Plus />}
          onClick={() => setLogDialog({})}
          className="ml-auto"
        >
          {t("liviere.activity.log.add")}
        </Button>
        {heatmap && (
          <span className="text-13 text-secondary">
            {t("liviere.activity.summary", {
              active: heatmap.summary.active_buckets,
              hours: heatmap.summary.active_hours.toLocaleString(currentLocale, { maximumFractionDigits: 2 }),
              events: heatmap.summary.events,
            })}
          </span>
        )}
      </div>

      {error ? (
        <p className="text-13 text-danger-primary">{t("liviere.activity.load_error")}</p>
      ) : isLoading && !heatmap ? (
        <Loader className="flex flex-col gap-1">
          {Array.from({ length: 7 }, (_, index) => (
            <Loader.Item key={index} height="12px" width="100%" />
          ))}
        </Loader>
      ) : heatmap ? (
        <ActivityGrid heatmap={heatmap} locale={currentLocale} selected={selected} onSelect={setSelected} />
      ) : null}

      <p className="text-12 text-tertiary">{t("liviere.activity.footnote", { timezone: timeZone })}</p>

      {selected && (
        <ActivityEventList
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          query={query}
          selected={selected}
          locale={currentLocale}
          onClose={() => setSelected(null)}
          canChange={canChange}
          onEdit={(entry) => setLogDialog({ entry })}
          onDelete={setDeleting}
        />
      )}

      {logDialog && (
        <ActivityLogModal
          workspaceSlug={workspaceSlug}
          projectId={projectId}
          entry={logDialog.entry}
          bucket={selected}
          onClose={() => setLogDialog(null)}
        />
      )}
      <AlertModalCore
        isOpen={!!deleting}
        handleClose={() => setDeleting(null)}
        handleSubmit={() => void deleteEntry()}
        isSubmitting={isDeleting}
        title={t("liviere.activity.log.delete_title")}
        content={t("liviere.activity.log.delete_confirm")}
        primaryButtonText={{ loading: t("deleting"), default: t("delete") }}
        secondaryButtonText={t("cancel")}
      />
    </div>
  );
});
