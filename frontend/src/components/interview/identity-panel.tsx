import { Identification } from "@/lib/api";
import { buttonClass } from "@/components/ui/button";

const SETTLED = new Set(["confirmed", "other_candidate", "low_confidence", "no_match", "no_face", "consent_required"]);
const CONFIDENT = new Set(["confirmed", "other_candidate"]);

export function faceVerdict(status: string): { title: string; detail: string } {
  if (status === "confirmed") {
    return { title: "Match", detail: "This face matches the photo on the CV." };
  }
  if (status === "checking" || status === "pending") {
    return { title: "Checking", detail: "Comparing the camera with the CV photo." };
  }
  if (status === "consent_required") {
    return { title: "Waiting", detail: "The candidate has not agreed to the face check yet." };
  }
  if (status === "other_candidate") {
    return { title: "Different person", detail: "This face matches a different candidate." };
  }
  if (status === "no_face") {
    return { title: "No face", detail: "No face was clear enough to compare." };
  }
  return { title: "No match", detail: "This face does not match the photo on the CV." };
}

export function IdentityPanel({
  identification,
  onAdmit,
  admitting = false,
}: {
  identification: Identification | null;
  onAdmit?: () => void;
  admitting?: boolean;
}) {
  const settled = Boolean(identification && (identification.concluded || SETTLED.has(identification.status)));
  if (!identification || !settled) {
    const verdict = faceVerdict(identification?.status || "pending");
    return (
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-mist">{verdict.title}</p>
        <p className="text-sm text-ivory">{identification?.message || verdict.detail}</p>
      </div>
    );
  }
  const verdict = faceVerdict(identification.status);
  const profile = CONFIDENT.has(identification.status) ? identification.profile : null;
  const score = profile?.pre_interview_score;
  const similarity = identification.invited_similarity ?? identification.similarity;
  return (
    <div className="space-y-4">
      <div className="space-y-1">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-peach">{verdict.title}</p>
        <p className="font-display text-2xl text-ivory">{identification.invited_name || "Candidate"}</p>
        <p className="text-sm leading-6 text-mist">{identification.message || verdict.detail}</p>
        {similarity != null ? <p className="text-sm text-ivory">Likeness {Math.round(similarity * 100)}%</p> : null}
      </div>
      {identification.admitted ? <p className="text-sm text-ivory">You let this candidate in.</p> : null}
      {onAdmit && identification.required && !identification.can_join ? (
        <button type="button" disabled={admitting} onClick={onAdmit} className={buttonClass()}>
          {admitting ? "Letting them in…" : "Let them in anyway"}
        </button>
      ) : null}
      {profile ? (
        <div className="space-y-2">
          <p className="text-sm font-medium text-ivory">{profile.full_name}</p>
          {profile.headline ? <p className="text-sm text-mist">{profile.headline}</p> : null}
          {profile.skills.length > 0 ? (
            <ul className="flex flex-wrap gap-1">
              {profile.skills.map((skill) => (
                <li key={skill} className="rounded-full border border-ivory/15 px-2 py-0.5 text-xs text-ivory">
                  {skill}
                </li>
              ))}
            </ul>
          ) : null}
          <p className="text-sm text-ivory">
            Pre-interview score {score == null ? "not scored" : `${Math.round(score * 100)}%`}
          </p>
          {profile.probe_areas.length > 0 ? (
            <div>
              <p className="text-xs uppercase tracking-wide text-mist">Areas to probe</p>
              <ul className="mt-1 list-disc pl-4 text-sm text-ivory">
                {profile.probe_areas.map((area) => (
                  <li key={area}>{area}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
