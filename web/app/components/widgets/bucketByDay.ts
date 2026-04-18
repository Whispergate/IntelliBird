import type { EventItem } from "@/app/api-client";

export function bucketByDay(items: EventItem[], days: number = 7): number[] {
  const now = Date.now();
  const buckets: number[] = new Array(days).fill(0);
  for (const item of items) {
    const age = now - new Date(item.observed_at).getTime();
    const day = Math.floor(age / 86_400_000);
    if (day >= 0 && day < days) buckets[days - 1 - day] += 1;
  }
  return buckets;
}
