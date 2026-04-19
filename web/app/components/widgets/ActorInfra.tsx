"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useRole } from "@/app/lib/role-context";
import { listEvents, type EventsQuery } from "@/app/api-client";
import { WidgetCard } from "./WidgetCard";
import { WidgetErrorBoundary } from "./WidgetErrorBoundary";
import { bucketByDay } from "./bucketByDay";

const LABEL = "ACTOR INFRASTRUCTURE (24H)";
const WINDOW_MS = 24 * 60 * 60 * 1000;

// tag_mode: "any" — matches events tagged actor OR c2
const WIDGET_FILTER_STATIC: Omit<EventsQuery, "observed_from"> = {
  tag: ["actor", "c2"],
  tag_mode: "any",
  limit: 1000,
};

function ActorInfraInner() {
  const role = useRole();
  const router = useRouter();
  const [state, setState] = useState<{
    count: number | null;
    sparkline: number[] | null;
    loading: boolean;
  }>({ count: null, sparkline: null, loading: true });

  useEffect(() => {
    let cancelled = false;
    const query: EventsQuery = {
      ...WIDGET_FILTER_STATIC,
      observed_from: new Date(Date.now() - WINDOW_MS).toISOString(),
    };
    listEvents(query, role)
      .then((res) => {
        if (!cancelled) {
          setState({
            count: res.items.length,
            sparkline: bucketByDay(res.items, 7),
            loading: false,
          });
        }
      })
      .catch(() => {
        if (!cancelled) setState({ count: 0, sparkline: null, loading: false });
      });
    return () => {
      cancelled = true;
    };
  }, [role]);

  function handleClick() {
    const filter: EventsQuery = {
      ...WIDGET_FILTER_STATIC,
      observed_from: new Date(Date.now() - WINDOW_MS).toISOString(),
    };
    router.push(`/events?preset=${encodeURIComponent(JSON.stringify(filter))}`);
  }

  return (
    <WidgetCard
      label={LABEL}
      count={state.count}
      sparkline={state.sparkline}
      loading={state.loading}
      onClick={handleClick}
    />
  );
}

export function ActorInfra() {
  return (
    <WidgetErrorBoundary label={LABEL}>
      <ActorInfraInner />
    </WidgetErrorBoundary>
  );
}
