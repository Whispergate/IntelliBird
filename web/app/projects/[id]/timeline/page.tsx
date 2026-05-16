import { getTimelineSeries, getTimelineHeatmap } from "@/app/api-client";
import TimelineClient from "./TimelineClient";

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ range_days?: string }>;
}

export default async function TimelinePage({ params, searchParams }: Props) {
  const { id: projectId } = await params;
  const { range_days } = await searchParams;
  const rangeDays = parseInt(range_days ?? "30", 10);

  const [series, heatmap] = await Promise.all([
    getTimelineSeries(projectId, rangeDays),
    getTimelineHeatmap(projectId, rangeDays),
  ]);

  return (
    <TimelineClient
      projectId={projectId}
      initialSeries={series}
      initialHeatmap={heatmap}
      initialRangeDays={rangeDays}
    />
  );
}
