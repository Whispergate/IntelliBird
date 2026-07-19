/**
 * /actors/[id] - (Threat Actors UI).
 *
 * RSC wrapper that fetches the actor server-side via `_apiFetch` and hands
 * it to the client component.
 */

import { _apiFetch, type ActorRead } from "@/app/api-client";
import ActorProfileClient from "./ActorProfileClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function ActorProfilePage({ params }: Props) {
  const { id } = await params;
  let actor: ActorRead | null = null;
  try {
    const res = await _apiFetch(`/api/actors/${id}`, { cache: "no-store" });
    if (res.ok) {
      actor = (await res.json()) as ActorRead;
    }
  } catch {
    actor = null;
  }

  if (!actor) {
    return (
      <div className="p-8 text-destructive">
        Could not load actor profile. Refresh the page or contact your administrator.
      </div>
    );
  }

  return <ActorProfileClient actor={actor} />;
}
