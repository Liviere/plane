/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Liviere/plane fork: the "Activity" page of a project. Rows are days (newest on top), columns are the
// 96 quarters of the day; the colour says how many actions happened in that quarter.

import { useMemo, useState } from "react";
import { observer } from "mobx-react";
import { useTranslation } from "@plane/i18n";
import { Loader } from "@plane/ui";
import { cn } from "@plane/utils";
import { MemberDropdown } from "@/components/dropdowns/member/dropdown";
import { ActivityEventList } from "./activity-events";
import { ActivityGrid } from "./activity-grid";
import { shiftDate, todayIn } from "./grid";
import { useActivityHeatmap } from "./use-activity";

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
        {heatmap && (
          <span className="ml-auto text-13 text-secondary">
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
        />
      )}
    </div>
  );
});
