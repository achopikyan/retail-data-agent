import { ReactNode, useEffect } from "react";

interface Props {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmText?: string;
  danger?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  description,
  confirmText = "Proceed",
  danger = false,
  onConfirm,
  onCancel,
}: Props) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in"
      style={{ background: "rgba(26, 24, 21, 0.55)" }}
      onClick={onCancel}
    >
      <div
        className="surface-elevated max-w-md w-full animate-fade-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 pt-5 pb-4 border-b border-rule">
          <div className="eyebrow mb-2">
            {danger ? "Destructive · Notice" : "Notice"}
          </div>
          <h2
            className="font-display text-[22px] leading-tight tracking-tight text-ink"
            style={{ fontVariationSettings: '"SOFT" 30, "opsz" 72' }}
          >
            {title}
          </h2>
        </div>
        {description && (
          <div className="px-6 py-4 text-[13.5px] leading-relaxed text-ink-2">
            {description}
          </div>
        )}
        <div className="px-6 py-3 flex justify-end gap-2 border-t border-rule bg-paper-sunken">
          <button className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            className={danger ? "btn-danger" : "btn-primary"}
            onClick={onConfirm}
          >
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  );
}
