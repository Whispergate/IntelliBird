"use client";

/**
 * MultiValueInput - tag-style input for adding/removing string values.
 * UI-SPEC §3a chip style.
 *
 * Usage:
 *   <MultiValueInput
 *     values={items}
 *     onChange={setItems}
 *     placeholder="Add asset..."
 *     disabled={readOnly}
 *   />
 *
 * Chip style: inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs
 * bg-card border-border - matches AISuggestionChip pattern.
 */

import { useState } from "react";
import { X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";

interface MultiValueInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
  className?: string;
}

export function MultiValueInput({
  values,
  onChange,
  placeholder = "Add item...",
  disabled = false,
  className = "",
}: MultiValueInputProps) {
  const [inputValue, setInputValue] = useState("");

  function addItem() {
    const trimmed = inputValue.trim();
    if (!trimmed || values.includes(trimmed)) return;
    onChange([...values, trimmed]);
    setInputValue("");
  }

  function removeItem(index: number) {
    onChange(values.filter((_, i) => i !== index));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter") {
      e.preventDefault();
      addItem();
    }
  }

  return (
    <div className={`space-y-2 ${className}`}>
      {/* Chips */}
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value, index) => (
            <span
              key={index}
              className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs bg-card border-border"
            >
              {value}
              {!disabled && (
                <button
                  type="button"
                  onClick={() => removeItem(index)}
                  className="text-muted-foreground hover:text-foreground transition-colors"
                  aria-label={`Remove ${value}`}
                >
                  <X size={12} />
                </button>
              )}
            </span>
          ))}
        </div>
      )}
      {/* Input row */}
      {!disabled && (
        <div className="flex items-center gap-2">
          <Input
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder={placeholder}
            className="h-8 text-sm"
            disabled={disabled}
          />
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addItem}
            disabled={!inputValue.trim()}
            className="shrink-0"
          >
            Add
          </Button>
        </div>
      )}
    </div>
  );
}
