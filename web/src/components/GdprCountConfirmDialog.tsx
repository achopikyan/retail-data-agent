import { useEffect, useState } from "react";

interface Props {
  open: boolean;
  expectedCount: number;
  substring: string;
  ownerSummary: { mine: number; others: number };
  onConfirm: (typedCount: number) => void;
  onCancel: () => void;
}

export default function GdprCountConfirmDialog({
  open,
  expectedCount,
  substring,
  ownerSummary,
  onConfirm,
  onCancel,
}: Props) {
  const [value, setValue] = useState("");

  useEffect(() => {
    if (open) setValue("");
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  if (!open) return null;
  const parsed = Number(value);
  const matches = !Number.isNaN(parsed) && parsed === expectedCount && value.trim() !== "";

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 animate-fade-in"
      style={{ background: "rgba(26, 24, 21, 0.6)" }}
      onClick={onCancel}
    >
      <div
        className="surface-elevated max-w-lg w-full animate-fade-up"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="px-6 pt-5 pb-4 border-b border-rule relative">
          {/* Decorative oxblood notch — like an official seal. */}
          <div className="absolute top-0 right-6 w-px h-full bg-oxblood" />
          <div className="eyebrow mb-2 !text-oxblood">
            GDPR · Cross-User Removal
          </div>
          <h2
            className="font-display text-[24px] leading-tight tracking-tight text-ink"
            style={{ fontVariationSettings: '"SOFT" 30, "WONK" 1, "opsz" 72' }}
          >
            Confirm by count
          </h2>
        </div>
        <div className="px-6 py-5 text-[13.5px] leading-relaxed text-ink-2 space-y-3">
          <p>
            This action will remove{" "}
            <span className="font-mono font-semibold text-ink tnum">
              {expectedCount}
            </span>{" "}
            saved report{expectedCount === 1 ? "" : "s"} whose title or body
            contains{" "}
            <code className="font-mono text-[12px] bg-paper-sunken px-1.5 py-0.5 border border-rule text-ink">
              {substring}
            </code>
            .
          </p>
          <div className="grid grid-cols-2 gap-px bg-rule border border-rule">
            <Stat label="Yours" value={ownerSummary.mine} tone="ink" />
            <Stat label="Other authors" value={ownerSummary.others} tone="oxblood" />
          </div>
          <p className="text-[12.5px]">
            To prevent fat-finger removals at high blast radius, type the
            exact number of reports below to authorise.
          </p>
          <div>
            <label className="block font-mono uppercase tracking-section text-[10px] text-ink-3 mb-1.5">
              ENTER COUNT
            </label>
            <input
              type="text"
              inputMode="numeric"
              autoComplete="off"
              placeholder={`type ${expectedCount}`}
              className="input font-mono text-[16px] tnum text-center"
              value={value}
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && matches) onConfirm(parsed);
              }}
              autoFocus
            />
          </div>
        </div>
        <div className="px-6 py-3 flex justify-end gap-2 border-t border-rule bg-paper-sunken">
          <button className="btn-secondary" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="btn-danger"
            disabled={!matches}
            onClick={() => onConfirm(parsed)}
          >
            Authorise removal of {expectedCount}
          </button>
        </div>
      </div>
    </div>
  );
}

interface StatProps {
  label: string;
  value: number;
  tone: "ink" | "oxblood";
}
function Stat({ label, value, tone }: StatProps) {
  return (
    <div className="bg-paper-raised px-3 py-2.5">
      <div className="font-mono uppercase tracking-section text-[9.5px] text-ink-3">
        {label}
      </div>
      <div
        className={`font-display text-[24px] leading-none tnum mt-1 ${
          tone === "oxblood" ? "text-oxblood" : "text-ink"
        }`}
        style={{ fontVariationSettings: '"opsz" 72' }}
      >
        {value}
      </div>
    </div>
  );
}
