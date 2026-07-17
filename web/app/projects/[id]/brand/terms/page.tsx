/**
 * /projects/[id]/brand/terms — async server component.
 *
 * Surface 5 entry point — delegates the interactive list + dialog to
 * `TermsClient`. No data fetch at the server level; the client owns the
 * list fetch so Observers / auth gates surface inside the rendered shell.
 */
import { TermsClient } from "./TermsClient";

export default async function Page({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <TermsClient projectId={id} />;
}
