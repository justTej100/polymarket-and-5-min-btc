"use client";

import { useMemo, useState } from "react";
import { useLiveStream } from "@/lib/hooks/useLiveStream";
import { PaperLeaderboard } from "@/components/PaperLeaderboard";
import { LeaderboardFilters, LeaderboardSort } from "@/components/LeaderboardFilters";
import type { PaperPublicState } from "@/lib/worker/paperTrading";

export default function LeaderboardPage() {
  const { data } = useLiveStream();
  const [sort, setSort] = useState<LeaderboardSort>("cash");
  const [positionedOnly, setPositionedOnly] = useState(false);

  const filteredPaper: PaperPublicState | null = useMemo(() => {
    if (!data?.paper) return null;

    let standings = [...data.paper.standings];

    if (positionedOnly) {
      standings = standings.filter((row) => row.openPositions.length > 0);
    }

    standings.sort((a, b) => {
      switch (sort) {
        case "windowPnl":
          return b.windowPnl - a.windowPnl;
        case "totalPnl":
          return b.totalPnl - a.totalPnl;
        case "wins":
          return b.wins - a.wins;
        case "cash":
        default:
          return b.bankroll - a.bankroll;
      }
    });

    return { ...data.paper, standings };
  }, [data?.paper, sort, positionedOnly]);

  return (
    <>
      <p className="page-title">Leaderboard — who's winning</p>
      <LeaderboardFilters
        sort={sort}
        onSortChange={setSort}
        positionedOnly={positionedOnly}
        onPositionedOnlyChange={setPositionedOnly}
      />
      {filteredPaper ? (
        <PaperLeaderboard paper={filteredPaper} />
      ) : (
        <p className="leaderboard-empty">Waiting for the live feed to connect…</p>
      )}
    </>
  );
}
