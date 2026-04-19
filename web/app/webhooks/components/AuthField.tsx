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
import type { WebhookFormValues } from "../lib/webhookSchema";

/**
 * Conditional auth field for Generic destination type only.
 * Returns null for Slack / Teams / Discord (auth is handled by the destination's
 * own mechanism — no operator-supplied credentials needed).
 *
 * For Generic destinations:
 * - Auth Type Select: None / Bearer token / Basic auth / Custom header
 * - Conditional sub-fields per selection
*/
export function AuthField() {
  const {
    register,
    watch,
    setValue,
    formState: { errors },
  } = useFormContext<WebhookFormValues>();

  const dtype = watch("destination_type");
  const atype = watch("auth_type") ?? "none";

  // Hidden for all non-generic destination types
  if (dtype !== "generic") return null;

  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor="auth_type">Auth</Label>
      <Select
        value={atype}
        onValueChange={(v) =>
          setValue("auth_type", v as WebhookFormValues["auth_type"], {
            shouldDirty: true,
          })
        }
      >
        <SelectTrigger id="auth_type">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none">None</SelectItem>
          <SelectItem value="bearer">Bearer token</SelectItem>
          <SelectItem value="basic">Basic auth</SelectItem>
          <SelectItem value="header">Custom header</SelectItem>
        </SelectContent>
      </Select>

      {atype === "bearer" && (
        <div className="flex flex-col gap-1">
          <Label htmlFor="auth_token">Token</Label>
          <Input
            id="auth_token"
            type="password"
            autoComplete="off"
            spellCheck={false}
            {...register("auth_token")}
          />
          {errors.auth_token && (
            <span className="text-xs text-destructive">
              {errors.auth_token.message}
            </span>
          )}
        </div>
      )}

      {atype === "basic" && (
        <div className="flex gap-2">
          <div className="flex-1 flex flex-col gap-1">
            <Label htmlFor="auth_username">Username</Label>
            <Input
              id="auth_username"
              autoComplete="off"
              spellCheck={false}
              {...register("auth_username")}
            />
            {errors.auth_username && (
              <span className="text-xs text-destructive">
                {errors.auth_username.message}
              </span>
            )}
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <Label htmlFor="auth_password">Password</Label>
            <Input
              id="auth_password"
              type="password"
              autoComplete="off"
              spellCheck={false}
              {...register("auth_password")}
            />
            {errors.auth_password && (
              <span className="text-xs text-destructive">
                {errors.auth_password.message}
              </span>
            )}
          </div>
        </div>
      )}

      {atype === "header" && (
        <div className="flex gap-2">
          <div className="flex-1 flex flex-col gap-1">
            <Label htmlFor="auth_header_name">Header name</Label>
            <Input
              id="auth_header_name"
              autoComplete="off"
              spellCheck={false}
              {...register("auth_header_name")}
            />
            {errors.auth_header_name && (
              <span className="text-xs text-destructive">
                {errors.auth_header_name.message}
              </span>
            )}
          </div>
          <div className="flex-1 flex flex-col gap-1">
            <Label htmlFor="auth_header_value">Header value</Label>
            <Input
              id="auth_header_value"
              type="password"
              autoComplete="off"
              spellCheck={false}
              {...register("auth_header_value")}
            />
            {errors.auth_header_value && (
              <span className="text-xs text-destructive">
                {errors.auth_header_value.message}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
