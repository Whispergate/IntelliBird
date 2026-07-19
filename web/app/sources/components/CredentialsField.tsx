"use client";

import { useFormContext } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { FeedType } from "@/app/api-client";
import type { SourceFormValues, TaxiiAuthScheme } from "../lib/sourceSchema";

/** Verbatim placeholder shown on all credential inputs in Edit mode.*/
const EDIT_PLACEHOLDER = "(unchanged - type to replace)";

type Props = {
  feed_type: FeedType;
  mode: "add" | "edit";
};

/**
 * Type-aware credentials field group.
 *
 * - RSS → renders nothing (null)
 * - NVD → single optional "NVD API Key" password input
 * - TAXII → auth-scheme Select + conditional username/password/token inputs
 *
 * All credential inputs are type="password", autoComplete="off", spellCheck={false}.
 * In Edit mode, inputs show the verbatim placeholder "(unchanged - type to replace)".
*/
export function CredentialsField({ feed_type, mode }: Props) {
  const {
    register,
    watch,
    setValue,
    formState: { errors },
  } = useFormContext<SourceFormValues>();

  const scheme = watch("taxii_scheme") ?? "none";
  const placeholder = mode === "edit" ? EDIT_PLACEHOLDER : undefined;

  // RSS: no credentials UI at all
  if (feed_type === "rss") return null;

  // NVD: single optional API key input
  if (feed_type === "nvd") {
    return (
      <div className="flex flex-col gap-1">
        <Label htmlFor="nvd_api_key">NVD API Key</Label>
        <Input
          id="nvd_api_key"
          type="password"
          autoComplete="off"
          spellCheck={false}
          placeholder={placeholder}
          {...register("nvd_api_key")}
        />
      </div>
    );
  }

  // TAXII: scheme Select + conditional inputs
  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <Label htmlFor="taxii_scheme">Auth scheme</Label>
        <Select
          value={scheme}
          onValueChange={(v) =>
            setValue("taxii_scheme", v as TaxiiAuthScheme, {
              shouldDirty: true,
            })
          }
        >
          <SelectTrigger id="taxii_scheme">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="none">None</SelectItem>
            <SelectItem value="basic">Basic</SelectItem>
            <SelectItem value="bearer">Bearer token</SelectItem>
            <SelectItem value="otx-apikey">OTX API key</SelectItem>
          </SelectContent>
        </Select>
      </div>

      {scheme === "basic" && (
        <>
          <div className="flex flex-col gap-1">
            <Label htmlFor="taxii_username">Username</Label>
            <Input
              id="taxii_username"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={placeholder}
              {...register("taxii_username")}
            />
            {errors.taxii_username && (
              <span className="text-xs text-destructive">
                {errors.taxii_username.message}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="taxii_password">Password</Label>
            <Input
              id="taxii_password"
              type="password"
              autoComplete="off"
              spellCheck={false}
              placeholder={placeholder}
              {...register("taxii_password")}
            />
            {errors.taxii_password && (
              <span className="text-xs text-destructive">
                {errors.taxii_password.message}
              </span>
            )}
          </div>
        </>
      )}

      {(scheme === "bearer" || scheme === "otx-apikey") && (
        <div className="flex flex-col gap-1">
          <Label htmlFor="taxii_token">
            {scheme === "bearer" ? "Bearer token" : "OTX API key"}
          </Label>
          <Input
            id="taxii_token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            placeholder={placeholder}
            {...register("taxii_token")}
          />
          {errors.taxii_token && (
            <span className="text-xs text-destructive">
              {errors.taxii_token.message}
            </span>
          )}
        </div>
      )}
    </div>
  );
}
