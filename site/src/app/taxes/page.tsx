import { Taxes } from "@/components/Taxes";
import { PageIntro } from "@/components/PageIntro";
export const metadata = { title: "Tax rules" };
export default function Page() {
  return (
    <>
      <PageIntro number="04 / TAXES" title="The date changes the bill.">
        Dubai’s effective-dated hotel tax stack. Read the status, confidence and source before relying on a
        rule.
      </PageIntro>
      <Taxes />
    </>
  );
}
