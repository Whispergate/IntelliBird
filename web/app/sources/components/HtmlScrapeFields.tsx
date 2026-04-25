"use client";

import { useFormContext } from "react-hook-form";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { SourceFormValues } from "../lib/sourceSchema";

type Props = {
  mode: "add" | "edit";
};

/**
 * Quick task 260425-ovt: HTML-scrape selector form, rendered only when
 * feed_type === "custom". Mirrors CredentialsField's idiom (FormProvider
 * context via useFormContext).
 *
 * The backend fetches the URL server-side and applies the CSS selectors —
 * pages that require JavaScript to render their items will yield nothing.
 * Operators are warned in the inline note plus docs/ops/html-scrape-sources.md.
 */
export function HtmlScrapeFields(_props: Props) {
  const {
    register,
    formState: { errors },
  } = useFormContext<SourceFormValues>();

  return (
    <div className="flex flex-col gap-3">
      <Alert>
        <AlertDescription className="text-xs">
          HTML scraping fetches the page and runs CSS selectors server-side.
          Pages that require JavaScript to render content will not work — use a
          feed-providing source instead. Use <code>selector@attr</code> to
          extract an attribute (e.g. <code>h2 a@href</code>); a plain selector
          extracts the element&apos;s text.
        </AlertDescription>
      </Alert>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_item_selector">Item selector (required)</Label>
        <Input
          id="scrape_item_selector"
          placeholder="article.post"
          {...register("scrape_item_selector")}
        />
        {errors.scrape_item_selector && (
          <span className="text-xs text-destructive">
            {errors.scrape_item_selector.message}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_title_selector">Title selector (required)</Label>
        <Input
          id="scrape_title_selector"
          placeholder="h2 a"
          {...register("scrape_title_selector")}
        />
        {errors.scrape_title_selector && (
          <span className="text-xs text-destructive">
            {errors.scrape_title_selector.message}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_link_selector">Link selector (required)</Label>
        <Input
          id="scrape_link_selector"
          placeholder="h2 a@href"
          {...register("scrape_link_selector")}
        />
        <span className="text-xs text-muted-foreground">
          Use <code>selector@attr</code> to extract an attribute. Plain selector
          extracts text.
        </span>
        {errors.scrape_link_selector && (
          <span className="text-xs text-destructive">
            {errors.scrape_link_selector.message}
          </span>
        )}
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_date_selector">Date selector</Label>
        <Input
          id="scrape_date_selector"
          placeholder="time@datetime"
          {...register("scrape_date_selector")}
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_date_format">Date format (strptime)</Label>
        <Input
          id="scrape_date_format"
          placeholder="%Y-%m-%dT%H:%M:%S%z"
          {...register("scrape_date_format")}
        />
        <span className="text-xs text-muted-foreground">
          Leave blank to auto-detect ISO-8601.
        </span>
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_summary_selector">Summary selector</Label>
        <Input
          id="scrape_summary_selector"
          placeholder=".excerpt"
          {...register("scrape_summary_selector")}
        />
      </div>

      <div className="flex flex-col gap-1">
        <Label htmlFor="scrape_max_items">Max items per poll</Label>
        <Input
          id="scrape_max_items"
          type="number"
          min={1}
          max={200}
          placeholder="50"
          {...register("scrape_max_items")}
        />
        <span className="text-xs text-muted-foreground">
          Defaults to 50; hard-capped at 200 server-side.
        </span>
      </div>
    </div>
  );
}
