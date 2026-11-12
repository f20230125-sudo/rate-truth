import { Accuracy } from "@/components/Accuracy";
import { PageIntro } from "@/components/PageIntro";
export const metadata = { title: "Price accuracy" };
export default function Page() {
  return (
    <>
      <PageIntro number="02 / ACCURACY" title="Does the landing price agree?">
        Compare generated feed prices with the booking engine. Inspect the difference, then introduce a fault.
      </PageIntro>
      <Accuracy />
    </>
  );
}
