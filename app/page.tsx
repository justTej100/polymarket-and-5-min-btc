import Link from "next/link";

export default function Home() {
  return (
    <>
      <p className="page-title">Home</p>
      <div className="home">
        <h1 className="home__title">Watching Polymarket's 5-min BTC Up/Down markets</h1>
        <p className="home__lede">
          9 independent, rule-based strategies watch Polymarket's 5-minute BTC
          Up/Down markets live — real Chainlink price feed, real order book,
          no refresh needed — and each trades a $1,000 imaginary bankroll
          against the real bid/ask so you can see, in real time, which rules
          would actually make money.
        </p>

        <div className="home__cards">
          <Link href="/board" className="home__card">
            <span className="home__card-title">Board</span>
            <span className="home__card-desc">
              The live market and every strategy's current call, plotted live.
            </span>
          </Link>
          <Link href="/leaderboard" className="home__card">
            <span className="home__card-title">Leaderboard</span>
            <span className="home__card-desc">
              Cash, P&amp;L, and win/loss for all 9 strategies, sortable and
              filterable.
            </span>
          </Link>
          <Link href="/strategy" className="home__card">
            <span className="home__card-title">Strategy</span>
            <span className="home__card-desc">
              What each strategy is actually watching for and why it's
              calling Up or Down.
            </span>
          </Link>
        </div>

        <a
          href="https://github.com/YOUR_USERNAME/polymarket-and-5-min-btc"
          target="_blank"
          rel="noreferrer"
          className="home__repo"
        >
          View the source on GitHub →
        </a>
      </div>
    </>
  );
}
