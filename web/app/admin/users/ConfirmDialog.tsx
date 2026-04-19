"use client";

import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

type Props = {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  confirmVariant?: "default" | "destructive" | "outline";
  dismissLabel: string;
  onConfirm: () => Promise<void> | void;
  onOpenChange: (o: boolean) => void;
};

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  confirmVariant = "default",
  dismissLabel,
  onConfirm,
  onOpenChange,
}: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <p className="py-4">{body}</p>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {dismissLabel}
          </Button>
          <Button variant={confirmVariant} onClick={() => onConfirm()}>
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
