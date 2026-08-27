"use client";

export type LeaderboardSort = "cash" | "windowPnl" | "totalPnl" | "wins";

const SORT_OPTIONS: { value: LeaderboardSort; label: string }[] = [
  { value: "cash", label: "Cash" },
  { value: "windowPnl", label: "This window" },
  { value: "totalPnl", label: "Total P&L" },
  { value: "wins", label: "Wins" },
];

export function LeaderboardFilters({
  sort,
  onSortChange,
  positionedOnly,
  onPositionedOnlyChange,
}: {
  sort: LeaderboardSort;
  onSortChange: (sort: LeaderboardSort) => void;
  positionedOnly: boolean;
  onPositionedOnlyChange: (value: boolean) => void;
}) {
  return (
    <div className="leaderboard-filters">
      <div className="leaderboard-filters__group">
        <span className="leaderboard-filters__label">Sort by</span>
        <div className="leaderboard-filters__pills">
          {SORT_OPTIONS.map((opt) => (
            <button
              key={opt.value}
              type="button"
              className={`leaderboard-filters__pill ${sort === opt.value ? "leaderboard-filters__pill--active" : ""}`}
              onClick={() => onSortChange(opt.value)}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <label className="leaderboard-filters__toggle">
        <input
          type="checkbox"
          checked={positionedOnly}
          onChange={(e) => onPositionedOnlyChange(e.target.checked)}
        />
        In a position now
      </label>
    </div>
  );
}
