import { Feeds } from "@/components/Feeds";
import { PageIntro } from "@/components/PageIntro";
export const metadata = { title: "Feeds" };
export default function Page() {
  return (
    <>
      <PageIntro number="03 / FEEDS" title="Published formats. Visible checks.">
        Generated hotel and rate feeds, with the schema, fetch date and validation result beside every file.
      </PageIntro>
      <Feeds />
    </>
  );
}
