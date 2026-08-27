import { redirect } from "next/navigation";

// Kept for backward compatibility with old links/bookmarks -- the live
// market + strategy board now lives at /board.
export default function ActivePage() {
  redirect("/board");
}
