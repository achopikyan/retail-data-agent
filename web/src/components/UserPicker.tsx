import { Role, useUser } from "../state/UserContext";

const PRESET_USERS = ["alice", "bob", "carol", "legal"];

export default function UserPicker() {
  const { userId, role, setUserId, setRole } = useUser();
  const isCustom = !PRESET_USERS.includes(userId);

  return (
    <div className="flex items-stretch border border-ink divide-x divide-ink bg-paper-raised shadow-paper">
      <div className="flex flex-col px-3 py-1.5">
        <span className="font-mono uppercase tracking-section text-[9px] text-ink-3 mb-0.5">
          BYLINE
        </span>
        <select
          aria-label="user"
          className="bg-transparent text-[13px] font-display font-medium text-ink focus:outline-none cursor-pointer pr-1"
          style={{ fontVariationSettings: '"SOFT" 30, "opsz" 36' }}
          value={isCustom ? "__custom" : userId}
          onChange={(e) => {
            if (e.target.value === "__custom") return;
            setUserId(e.target.value);
          }}
        >
          {PRESET_USERS.map((u) => (
            <option key={u} value={u}>
              {u}
            </option>
          ))}
          <option value="__custom" disabled>
            {isCustom ? userId : "(custom)"}
          </option>
        </select>
      </div>
      <div className="flex flex-col px-3 py-1.5">
        <span className="font-mono uppercase tracking-section text-[9px] text-ink-3 mb-0.5">
          DESK
        </span>
        <select
          aria-label="role"
          className={`bg-transparent text-[13px] font-mono uppercase tracking-wider font-medium focus:outline-none cursor-pointer pr-1 ${
            role === "gdpr_officer" ? "text-oxblood" : "text-ink"
          }`}
          value={role}
          onChange={(e) => setRole(e.target.value as Role)}
        >
          <option value="manager">manager</option>
          <option value="gdpr_officer">gdpr</option>
        </select>
      </div>
    </div>
  );
}
