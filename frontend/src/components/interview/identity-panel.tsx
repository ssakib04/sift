import { Identification } from "@/lib/api";

const SETTLED = new Set(["confirmed", "other_candidate", "low_confidence", "no_match", "no_face", "consent_required"]);
const CONFIDENT = new Set(["confirmed", "other_candidate"]);

export function IdentityPanel({ identification }: { identification: Identification | null }) {
  const settled = Boolean(identification && (identification.concluded || SETTLED.has(identification.status)));
  if (!identification || !settled) {
    return <p className="text-sm text-mist">{identification?.message || "Waiting for the face check."}</p>;
  }
  const profile = CONFIDENT.has(identification.status) ? identification.profile : null;
  const score = profile?.pre_interview_score;
  return (
    <div className="space-y-3">
      <p className="text-sm text-ivory">{identification.message}</p>
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
