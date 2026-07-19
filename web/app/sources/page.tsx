import type { Source } from "../api-client";
import { fetchSources } from "../api-client";
import { SourcesClient } from "./SourcesClient";

export default async function SourcesPage() {
  let sources: Source[] = [];
  try {
    sources = await fetchSources();
  } catch {
    sources = [];
  }
  return <SourcesClient initialSources={sources} />;
}
