"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { toast } from "sonner";

import {
  listEvents,
  getPreset,
  type EventItem,
} from "@/app/api-client";
import { useRole } from "@/app/lib/role-context";
import { seedPresets } from "@/app/lib/seed-presets";
import { BlueWidgets, RedWidgets } from "@/app/components/widgets";
import { DashboardEventsList } from "@/app/components/DashboardEventsList";
import { EventDetailDrawer } from "@/app/components/EventDetailDrawer";

export function DashboardClient() {
  const role = useRole();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const selectedEventId = searchParams.get("event");

  const [items, setItems] = useState<EventItem[] | null>(null);
  const [loading, setLoading] = useState(true);

  // Seed preset on first mount per session (role switches seed the new role lazily).
  useEffect(() => {
    seedPresets(role);
  }, [role]);

  // Fetch events list - owns the state so drawer can derive prev/next from it.
  useEffect(() => {
    let cancelled = false;
    const presetName = `default-${role}`;
    (async () => {
      try {
        let presetQuery: Record<string, unknown> = {};
        try {
          const preset = await getPreset(presetName);
          presetQuery = preset.query_params ?? {};
        } catch {
          // preset seed is racing - proceed with empty query
        }
        const res = await listEvents(
          { ...(presetQuery as object), limit: 25 },
          role,
        );
        if (!cancelled) {
          setItems(res.items);
          setLoading(false);
        }
      } catch (err) {
        if (!cancelled) {
          toast.error("Failed to load events.");
          setItems([]);
          setLoading(false);
        }
        // eslint-disable-next-line no-console
        console.warn("[DashboardClient] listEvents failed", err);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [role]);

  const currentIndex = useMemo(() => {
    if (!selectedEventId || !items) return 0;
    const idx = items.findIndex((e) => e.id === selectedEventId);
    return idx < 0 ? 0 : idx;
  }, [selectedEventId, items]);

  const { prevEventId, nextEventId } = useMemo(() => {
    if (!items || !selectedEventId) return { prevEventId: null, nextEventId: null };
    const idx = items.findIndex((e) => e.id === selectedEventId);
    if (idx < 0) return { prevEventId: null, nextEventId: null };
    return {
      prevEventId: idx > 0 ? items[idx - 1].id : null,
      nextEventId: idx < items.length - 1 ? items[idx + 1].id : null,
    };
  }, [selectedEventId, items]);

  function onNavigate(id: string) {
    router.replace(`${pathname}?event=${encodeURIComponent(id)}`);
  }

  return (
    <>
      <div className="flex flex-col gap-6">
        {role === "blue" ? <BlueWidgets /> : <RedWidgets />}
        <DashboardEventsList items={items ?? undefined} loading={loading} />
      </div>
      <EventDetailDrawer
        prevEventId={prevEventId}
        nextEventId={nextEventId}
        currentIndex={currentIndex}
        totalCount={items?.length ?? 0}
        onNavigate={onNavigate}
      />
    </>
  );
}
