import { ButtonLink } from "@/components/ui/button";
import { GuestFrame } from "@/components/ui/guest-frame";
import { PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";

export default function NotFound() {
  return (
    <GuestFrame>
      <Panel className="w-full">
        <div className="space-y-6 p-6">
          <PageHeader
            eyebrow="Sift"
            title="This page is not here"
            lede="The address does not match a recruiter page or a guest link."
          />
          <ButtonLink href="/">Back to the desk</ButtonLink>
        </div>
      </Panel>
    </GuestFrame>
  );
}
