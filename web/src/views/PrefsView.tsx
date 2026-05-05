import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { allowedKeys, getPrefs, setPref } from "../api/prefs";
import { useUser } from "../state/UserContext";

const PREDEFINED_VALUES: Record<string, string[]> = {
  report_format: ["table", "bullets", "prose"],
  preferred_currency: ["USD", "EUR", "ILS", "GBP"],
};

const KEY_LABEL: Record<string, string> = {
  report_format: "Standing format",
  default_time_window: "Default window",
  preferred_currency: "Currency",
};

export default function PrefsView() {
  const { userId, role } = useUser();
  const qc = useQueryClient();

  const prefsQ = useQuery({
    queryKey: ["prefs", userId],
    queryFn: () => getPrefs({ userId, role }),
  });

  const keysQ = useQuery({
    queryKey: ["prefs-keys"],
    queryFn: () => allowedKeys({ userId, role }),
  });

  const setMut = useMutation({
    mutationFn: (body: { key: string; value: string }) =>
      setPref({ userId, role }, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["prefs", userId] }),
    onError: (err: Error) => alert(err.message),
  });

  const [draft, setDraft] = useState<Record<string, string>>({});
  const current = prefsQ.data?.prefs ?? {};

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-3">
        <div>
          <div className="eyebrow">§ 04 — Standing Orders</div>
          <h2
            className="display mt-1"
            style={{ fontVariationSettings: '"SOFT" 50, "opsz" 72' }}
          >
            Your preferences
          </h2>
        </div>
        <div className="hidden md:block text-right">
          <div className="font-mono uppercase tracking-section text-[10px] text-ink-3">
            For
          </div>
          <div
            className="font-display text-[20px] tracking-tight text-ink"
            style={{ fontVariationSettings: '"SOFT" 30, "opsz" 48' }}
          >
            {userId}
          </div>
        </div>
      </div>

      <p className="lede max-w-2xl">
        The desk reads these on every report. Implicit hints in your questions
        (“just the table”, “in bullets”) update them automatically — set a
        baseline here.
      </p>

      <div className="grid lg:grid-cols-2 gap-px bg-rule border border-rule">
        {keysQ.data?.map((k) => {
          const value = draft[k] ?? current[k] ?? "";
          const options = PREDEFINED_VALUES[k];
          const dirty = draft[k] !== undefined && draft[k] !== current[k];
          return (
            <div key={k} className="bg-paper-raised p-5 space-y-3">
              <div className="flex items-baseline justify-between">
                <div>
                  <div className="font-display text-[18px] tracking-tight text-ink"
                       style={{ fontVariationSettings: '"SOFT" 30, "opsz" 36' }}>
                    {KEY_LABEL[k] ?? k}
                  </div>
                  <div className="font-mono uppercase tracking-section text-[10px] text-ink-3 mt-0.5">
                    {k}
                  </div>
                </div>
                <div className="font-mono text-[11px] text-ink-3 tnum">
                  current:{" "}
                  <span className={current[k] ? "text-ink" : "italic text-ink-4"}>
                    {current[k] ?? "unset"}
                  </span>
                </div>
              </div>
              <div className="flex items-stretch border border-rule">
                {options ? (
                  <select
                    className="flex-1 bg-paper-raised px-3 py-2 text-[13px] focus:outline-none cursor-pointer"
                    value={value}
                    onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                  >
                    <option value="">(unset)</option>
                    {options.map((o) => (
                      <option key={o} value={o}>
                        {o}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    className="flex-1 bg-paper-raised px-3 py-2 text-[13px] focus:outline-none"
                    value={value}
                    onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                    placeholder="(unset)"
                  />
                )}
                <button
                  className={`px-4 text-[12px] font-medium tracking-tight border-l border-rule transition-colors disabled:opacity-30 disabled:cursor-not-allowed ${
                    dirty ? "bg-ink text-paper hover:bg-oxblood" : "bg-paper-sunken text-ink-3"
                  }`}
                  disabled={!dirty || !value}
                  onClick={() => {
                    setMut.mutate({ key: k, value });
                    setDraft((d) => {
                      const n = { ...d };
                      delete n[k];
                      return n;
                    });
                  }}
                >
                  Save
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
