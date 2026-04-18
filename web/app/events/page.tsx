import { Suspense } from "react";
import { EventsClient } from "./EventsClient";

export default function EventsPage() {
  return (
    <Suspense
      fallback={
        <div className="p-6 text-muted-foreground">Loading events…</div>
      }
    >
      <EventsClient />
    </Suspense>
  );
}
