import { useQuery } from "@tanstack/react-query";

import { listPersonas } from "../api/personas";
import { useUser } from "../state/UserContext";

export default function PersonasView() {
  const { userId, role } = useUser();
  const { data } = useQuery({
    queryKey: ["personas"],
    queryFn: () => listPersonas({ userId, role }),
    refetchInterval: 5_000,
  });

  return (
    <section className="space-y-6">
      <div className="flex items-baseline justify-between gap-4 border-b border-rule pb-3">
        <div>
          <div className="eyebrow">§ 05 — Editorial Voices</div>
          <h2
            className="display mt-1"
            style={{ fontVariationSettings: '"SOFT" 50, "opsz" 72' }}
          >
            Personas
          </h2>
        </div>
      </div>

      <div className="lede max-w-2xl">
        Personas live in{" "}
        <code className="font-mono not-italic text-[13px] bg-paper-sunken px-1.5 py-0.5 border border-rule text-ink">
          config/personas.yaml
        </code>
        . Edit on disk and the next briefing picks up the change — the desk
        re-reads on every report. This page is read-only by design (allowing
        a logged-in browser to rewrite the system prompt would be a footgun).
      </div>

      {!data && (
        <div className="surface p-8 text-center font-display italic text-ink-3">
          loading…
        </div>
      )}

      {data && (
        <div className="grid md:grid-cols-2 gap-4 stagger">
          {data.personas.map((p) => {
            const active = p.name === data.active;
            return (
              <article
                key={p.name}
                className={`surface relative ${
                  active ? "ring-1 ring-oxblood ring-offset-2 ring-offset-paper" : ""
                }`}
              >
                {active && (
                  <div className="absolute -top-2.5 left-4">
                    <span className="badge-blood">In voice</span>
                  </div>
                )}
                <header className="px-5 pt-5 pb-3 border-b border-rule">
                  <div className="eyebrow !text-ink-3">Voice</div>
                  <h3
                    className="font-display text-[26px] leading-tight tracking-tight mt-1.5 text-ink"
                    style={{
                      fontVariationSettings: active
                        ? '"SOFT" 30, "WONK" 1, "opsz" 96'
                        : '"SOFT" 30, "WONK" 0, "opsz" 96',
                    }}
                  >
                    {p.name}
                  </h3>
                  <p className="font-display italic text-[14px] text-ink-2 mt-1"
                     style={{ fontVariationSettings: '"SOFT" 100, "opsz" 24' }}>
                    {p.description}
                  </p>
                </header>
                <pre className="px-5 py-4 text-[12.5px] leading-relaxed whitespace-pre-wrap font-mono text-ink-2">
                  {p.instructions}
                </pre>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
