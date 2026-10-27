import assert from "node:assert/strict";
import { test } from "node:test";
import {
  agentPresence,
  avatarPresentation,
  elementMuted,
  isAgentAudio,
  releaseAvatar,
  shouldHandAudioToAvatar,
} from "./agent-audio.ts";

test("the interviewer presence is listening, thinking, or speaking", () => {
  assert.equal(agentPresence("speaking"), "Speaking");
  assert.equal(agentPresence("thinking"), "Thinking");
  assert.equal(agentPresence("listening"), "Listening");
  assert.equal(agentPresence("waiting"), "Listening");
  assert.equal(agentPresence(null), "Listening");
});

test("agent audio is the remote track that is not the candidate or the recruiter", () => {
  assert.equal(isAgentAudio("sift-interviewer", "audio"), true);
  assert.equal(isAgentAudio("agent-AJ_123", "audio"), true);
  assert.equal(isAgentAudio("candidate", "audio"), false);
  assert.equal(isAgentAudio("recruiter", "audio"), false);
  assert.equal(isAgentAudio("sift-interviewer", "video"), false);
});

test("the still portrait is used when the scene cannot run", () => {
  const ready = { webgl: true, reducedMotion: false, modelAvailable: true, failed: false };
  assert.equal(avatarPresentation(ready), "scene");
  assert.equal(avatarPresentation({ ...ready, webgl: false }), "portrait");
  assert.equal(avatarPresentation({ ...ready, reducedMotion: true }), "portrait");
  assert.equal(avatarPresentation({ ...ready, modelAvailable: false }), "portrait");
  assert.equal(avatarPresentation({ ...ready, failed: true }), "portrait");
});

test("the audio element stays audible until the scene owns the agent track", () => {
  assert.equal(
    shouldHandAudioToAvatar({ presentation: "scene", sceneReady: true, hasAgentAudio: true }),
    true,
  );
  assert.equal(
    shouldHandAudioToAvatar({ presentation: "scene", sceneReady: false, hasAgentAudio: true }),
    false,
  );
  assert.equal(
    shouldHandAudioToAvatar({ presentation: "portrait", sceneReady: true, hasAgentAudio: true }),
    false,
  );
  assert.equal(
    shouldHandAudioToAvatar({ presentation: "scene", sceneReady: true, hasAgentAudio: false }),
    false,
  );
  assert.equal(elementMuted("avatar"), true);
  assert.equal(elementMuted("element"), false);
});

test("releasing the scene detaches the stream before disposing it and returns audio to the element", () => {
  const calls: string[] = [];
  const owner = releaseAvatar({
    detachStream() {
      calls.push("detach");
    },
    dispose() {
      calls.push("dispose");
    },
  });
  assert.deepEqual(calls, ["detach", "dispose"]);
  assert.equal(owner, "element");
  assert.equal(releaseAvatar(null), "element");
});
