/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */

// Liviere/plane fork: actions of one heatmap quarter, with links to what they changed.

import { useEffect, useRef } from "react";
import Link from "next/link";
import useSWR from "swr";
import { X } from "lucide-react";
import { useTranslation } from "@plane/i18n";
import { Avatar, Loader } from "@plane/ui";
import { getFileURL } from "@plane/utils";
import { projectActivityService } from "./activity.service";
import type { TSelectedBucket } from "./activity-root";
import { slotBounds, slotRange } from "./grid";
import type { TActivityEvent, TActivityQuery } from "./types";

type Props = {
  workspaceSlug: string;
  projectId: string;
  query: TActivityQuery;
  selected: TSelectedBucket;
  locale: string;
  onClose: () => void;
};

const OBJECT_PATHS: Record<string, string> = { cycle: "cycles", module: "modules", view: "views" };

function eventTarget(event: TActivityEvent, workspaceSlug: string, projectId: string) {
  if (event.issue) {
    const label = [event.issue.identifier, event.issue.name].filter(Boolean).join(" ");
    const href = event.issue.identifier ? `/${workspaceSlug}/browse/${event.issue.identifier}/` : null;
    return { label, href, deleted: event.issue.deleted };
  }
  if (event.page) {
    return {
      label: event.page.name,
      href: `/${workspaceSlug}/projects/${projectId}/pages/${event.page.id}`,
      deleted: event.page.deleted,
    };
  }
  if (event.object) {
    const path = OBJECT_PATHS[event.source];
    return {
      label: event.object.name,
      href: path ? `/${workspaceSlug}/projects/${projectId}/${path}/${event.object.id}` : null,
      deleted: event.object.deleted,
    };
  }
  return null;
}

export function ActivityEventList(props: Props) {
  const { workspaceSlug, projectId, query, selected, locale, onClose } = props;
  const { t } = useTranslation();
  const { start, end } = slotBounds(selected.date, selected.slot);
  const { data, error, isLoading } = useSWR(
    `LIVIERE_ACTIVITY_EVENTS_${projectId}_${query.tz}_${query.actor ?? ""}_${start}`,
    () => projectActivityService.getEvents(workspaceSlug, projectId, { ...query, start, end }),
    { revalidateOnFocus: false }
  );
  // 24-hour clock, like the hour labels of the grid
  const time = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: query.tz,
  });
  const sectionRef = useRef<HTMLElement>(null);
  // The list opens below the grid; bring it into view
  useEffect(() => {
    sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selected.date, selected.slot]);
  const day = new Intl.DateTimeFormat(locale, { dateStyle: "full", timeZone: "UTC" });

  return (
    <section ref={sectionRef} className="rounded-md border border-subtle bg-layer-1 p-4">
      <header className="mb-3 flex items-center justify-between gap-2">
        <h3 className="text-14 font-medium text-primary">
          {day.format(new Date(`${selected.date}T00:00:00Z`))}, {slotRange(selected.slot)}
        </h3>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("liviere.activity.close")}
          className="rounded-sm p-1 text-tertiary hover:bg-layer-transparent-hover"
        >
          <X className="size-4" />
        </button>
      </header>
      {error ? (
        <p className="text-13 text-danger-primary">{t("liviere.activity.load_error")}</p>
      ) : isLoading || !data ? (
        <Loader className="flex flex-col gap-2">
          <Loader.Item height="20px" width="100%" />
          <Loader.Item height="20px" width="80%" />
        </Loader>
      ) : data.results.length === 0 ? (
        <p className="text-13 text-tertiary">{t("liviere.activity.no_activity")}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {data.results.map((event) => {
            const target = eventTarget(event, workspaceSlug, projectId);
            return (
              <li key={event.id} className="flex items-center gap-2 text-13">
                <span className="w-12 shrink-0 text-tertiary">{time.format(new Date(event.occurred_at))}</span>
                {event.actor ? (
                  <Avatar name={event.actor.display_name} src={getFileURL(event.actor.avatar_url ?? "")} size="sm" />
                ) : null}
                <span className="shrink-0 text-secondary">{event.actor?.display_name ?? "—"}</span>
                <span className="shrink-0 text-primary">{t(`liviere.activity.kinds.${event.kind}`)}</span>
                {target && (
                  <span className="min-w-0 truncate text-tertiary">
                    {target.href && !target.deleted ? (
                      <Link href={target.href} className="hover:text-primary hover:underline">
                        {target.label || t("liviere.activity.untitled")}
                      </Link>
                    ) : (
                      <span className="line-through">{target.label || t("liviere.activity.deleted")}</span>
                    )}
                  </span>
                )}
              </li>
            );
          })}
          {data.next_page_results && (
            <li className="text-12 text-tertiary">{t("liviere.activity.more_events", { count: data.total_count })}</li>
          )}
        </ul>
      )}
    </section>
  );
}
