import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { ModalRunStatus } from "../../api/types";

const STATUS_STYLES: Record<ModalRunStatus, string> = {
  queued: "text-muted-foreground border-muted-foreground/20 bg-muted/20",
  running: "text-primary border-primary/20 bg-primary/10",
  complete: "text-[--positive] border-[--positive]/20 bg-[--positive]/10",
  degraded: "text-[--warning] border-[--warning]/20 bg-[--warning]/10",
  failed: "text-[--negative] border-[--negative]/20 bg-[--negative]/10",
};

export function StatusBadge({ status, className }: { status: ModalRunStatus; className?: string }) {
  const style = STATUS_STYLES[status];
  return (
    <Badge variant="outline" className={cn("text-[9px] uppercase tracking-wider", style, className)}>
      {status}
    </Badge>
  );
}
