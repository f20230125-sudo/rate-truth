import { Hotels } from "@/components/Hotels";
import { PageIntro } from "@/components/PageIntro";
export const metadata = { title: "Hotels" };
export default function Page() {
  return (
    <>
      <PageIntro number="01 / HOTELS" title="Real places. Itemised stays.">
        Hotel facts from OpenStreetMap, rates from a synthetic supplier engine. Open a row to inspect both.
      </PageIntro>
      <Hotels />
    </>
  );
}
