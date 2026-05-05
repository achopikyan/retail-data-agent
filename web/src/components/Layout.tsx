import { NavLink, Outlet } from "react-router-dom";

import PersonaBadge from "./PersonaBadge";
import UserPicker from "./UserPicker";

const tabs = [
  { to: "/chat", label: "Briefing", index: "01" },
  { to: "/reports", label: "Archive", index: "02" },
  { to: "/audit", label: "Ledger", index: "03" },
  { to: "/prefs", label: "Preferences", index: "04" },
  { to: "/personas", label: "Voices", index: "05" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex flex-col">
      {/* ============================== MASTHEAD ============================== */}
      <header className="border-b border-ink/90 bg-paper">
        {/* Top thin ribbon — date & ticker-like meta. */}
        <div className="border-b border-rule">
          <div className="mx-auto max-w-[1200px] px-6 py-1.5 flex items-center justify-between text-[10.5px] font-mono uppercase tracking-section text-ink-3">
            <div className="flex items-center gap-3">
              <span>Vol. I</span>
              <span className="text-rule-strong">·</span>
              <span>No. 042</span>
              <span className="text-rule-strong">·</span>
              <span className="hidden sm:inline">
                {new Date().toLocaleDateString("en-GB", {
                  weekday: "long",
                  day: "2-digit",
                  month: "long",
                  year: "numeric",
                })}
              </span>
            </div>
            <div className="hidden md:flex items-center gap-3">
              <span>BigQuery · thelook_ecommerce</span>
              <span className="text-rule-strong">·</span>
              <span>Gemini 2.5 Pro</span>
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-verdigris animate-pulse-soft" />
                Live
              </span>
            </div>
          </div>
        </div>

        {/* Main masthead row — display title + meta. */}
        <div className="mx-auto max-w-[1200px] px-6 py-5 grid grid-cols-1 lg:grid-cols-12 gap-y-4 gap-x-6 items-end">
          <div className="lg:col-span-7">
            <div className="eyebrow mb-2">An Internal Research Desk</div>
            <h1 className="display-lg leading-[0.95]">
              The Retail Desk
              <span className="text-oxblood">.</span>
            </h1>
            <p className="lede mt-2 max-w-xl">
              A working brief on customers, orders, and inventory — drafted on
              demand, fact-checked against the warehouse.
            </p>
          </div>
          <div className="lg:col-span-5 flex flex-col items-start lg:items-end gap-3">
            <PersonaBadge />
            <UserPicker />
          </div>
        </div>

        {/* Section nav — newspaper section index. */}
        <nav className="border-t border-rule">
          <div className="mx-auto max-w-[1200px] px-6 -mb-px flex items-stretch overflow-x-auto">
            {tabs.map((t) => (
              <NavLink
                key={t.to}
                to={t.to}
                className={({ isActive }) =>
                  `group relative flex items-baseline gap-2 px-4 py-2.5 -mb-px
                   border-b-2 whitespace-nowrap
                   transition-colors duration-150
                   ${
                     isActive
                       ? "border-oxblood text-ink"
                       : "border-transparent text-ink-3 hover:text-ink"
                   }`
                }
              >
                <span className="font-mono text-[10px] tracking-wider text-ink-4 group-hover:text-oxblood transition-colors">
                  §{t.index}
                </span>
                <span className="font-display text-[15px] tracking-tight"
                      style={{ fontVariationSettings: '"SOFT" 30, "opsz" 36' }}>
                  {t.label}
                </span>
              </NavLink>
            ))}
          </div>
        </nav>
      </header>

      {/* ================================ MAIN ================================ */}
      <main className="flex-1">
        <div className="mx-auto max-w-[1200px] px-6 py-8 animate-fade-in">
          <Outlet />
        </div>
      </main>

      {/* ============================== COLOPHON ============================== */}
      <footer className="border-t border-rule bg-paper">
        <div className="mx-auto max-w-[1200px] px-6 py-4 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-[11px] text-ink-3">
          <div className="font-mono tracking-wider uppercase">
            Colophon — set in <span className="font-display normal-case tracking-normal text-ink-2">Fraunces</span>
            {" & "}
            <span className="font-sans normal-case tracking-normal text-ink-2">IBM Plex</span>.
          </div>
          <div className="font-mono tracking-wider uppercase">
            Header identity · No real auth · PII enforced server-side
          </div>
        </div>
      </footer>
    </div>
  );
}
