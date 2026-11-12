import { Method } from "@/components/Method";
import { PageIntro } from "@/components/PageIntro";
export const metadata = { title: "Method & connect" };
export default function Page() {
  return (
    <>
      <PageIntro number="05 / METHOD" title="Evidence before claims.">
        The evaluation record, the limits of the system, and the endpoint for your own MCP client.
      </PageIntro>
      <Method />
    </>
  );
}
