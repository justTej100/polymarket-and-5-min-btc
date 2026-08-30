"use client";

import { useLiveStream } from "@/lib/hooks/useLiveStream";
import { StrategyExplainer } from "@/components/StrategyExplainer";

export default function StrategyPage() {
  const { data } = useLiveStream();

  return (
    <>
      <p className="page-title">Strategy — what each rule-based strategy is watching for</p>
      <p className="strategy-intro">
        Each strategy below reacts to the same live market feed as the Board
        tab. The badges here update in real time too. For the full visual
        picture of who's leaning Up vs Down right now, head to Board; this
        page is for understanding the "why" behind each call.
      </p>
      <StrategyExplainer signals={data?.signals ?? []} />
    </>
  );
}
