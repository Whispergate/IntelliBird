"use client";

import { useFormContext } from "react-hook-form";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import {
  RETENTION_PRESETS,
  type RetentionPresetKey,
  type SourceFormValues,
} from "../lib/sourceSchema";

/**
 * Retention Preset Picker — 5 radio options.
 *
 * Selecting "Custom" reveals:
 *  - Hot retention (days) number input
 *  - Archive policy Select
 */
export function RetentionPresetPicker() {
  const {
    register,
    watch,
    setValue,
    formState: { errors },
  } = useFormContext<SourceFormValues>();

  const preset = watch("retention_preset") ?? "standard";

  return (
    <div className="flex flex-col gap-2">
      <Label>Retention</Label>
      <RadioGroup
        value={preset}
        onValueChange={(v) =>
          setValue("retention_preset", v as RetentionPresetKey, {
            shouldDirty: true,
          })
        }
        className="flex flex-col gap-1"
      >
        {RETENTION_PRESETS.map((p) => (
          <div key={p.key} className="flex items-center gap-2">
            <RadioGroupItem value={p.key} id={`preset-${p.key}`} />
            <Label htmlFor={`preset-${p.key}`} className="text-sm font-normal">
              {p.label}
              {p.key !== "custom" && (
                <span className="text-xs text-muted-foreground ml-2">
                  ({p.hotDays} days, {p.archivePolicy})
                </span>
              )}
            </Label>
          </div>
        ))}
      </RadioGroup>

      {preset === "custom" && (
        <div className="flex flex-col gap-3 pl-6 mt-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="hot_retention_days_custom">
              Hot retention (days)
            </Label>
            <Input
              id="hot_retention_days_custom"
              type="number"
              min={1}
              max={3650}
              {...register("hot_retention_days_custom")}
            />
            {errors.hot_retention_days_custom && (
              <span className="text-xs text-destructive">
                {errors.hot_retention_days_custom.message}
              </span>
            )}
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="archive_policy_custom">Archive policy</Label>
            <Select
              value={watch("archive_policy_custom") ?? "drop"}
              onValueChange={(v) =>
                setValue("archive_policy_custom", v as "keep" | "drop" | "move-to-cold", {
                  shouldDirty: true,
                })
              }
            >
              <SelectTrigger id="archive_policy_custom">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="keep">keep</SelectItem>
                <SelectItem value="drop">drop</SelectItem>
                <SelectItem value="move-to-cold">move-to-cold</SelectItem>
              </SelectContent>
            </Select>
            {errors.archive_policy_custom && (
              <span className="text-xs text-destructive">
                {errors.archive_policy_custom.message}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
