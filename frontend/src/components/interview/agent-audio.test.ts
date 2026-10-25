import assert from "node:assert/strict";
import { test } from "node:test";
import { blendField, isAgentAudio, presenceCaption, presenceField, presenceMood } from "./agent-audio.ts";

test("agent audio is the remote track that is not the candidate or the recruiter", () => {
  assert.equal(isAgentAudio("sift-interviewer", "audio"), true);
  assert.equal(isAgentAudio("agent-AJ_123", "audio"), true);
  assert.equal(isAgentAudio("candidate", "audio"), false);
  assert.equal(isAgentAudio("recruiter", "audio"), false);
  assert.equal(isAgentAudio("sift-interviewer", "video"), false);
});

test("her voice pushes the network outward and a quiet mood draws it inward", () => {
  const listening = presenceField("listening", 0, false);
  const speaking = presenceField("listening", 0.8, false);
  const thinking = presenceField("thinking", 0, false);
  const waiting = presenceField("waiting", 0, false);
  const still = presenceField("speaking", 0.8, true);
  assert.equal(listening.mood, "listening");
  assert.ok(listening.flow < 0);
  assert.equal(speaking.mood, "speaking");
  assert.ok(speaking.flow > 0);
  assert.ok(speaking.energy > listening.energy);
  assert.ok(thinking.gather > listening.gather);
  assert.ok(thinking.flow < 0);
  assert.ok(waiting.energy < listening.energy);
  assert.equal(still.drift, 0);
  assert.equal(still.mood, "speaking");
});

test("a thinking signal stays thinking until her voice actually arrives", () => {
  assert.equal(presenceMood("thinking"), "thinking");
  assert.equal(presenceMood("later"), "listening");
  assert.equal(presenceField("thinking", 0, false, "thinking").mood, "thinking");
  assert.equal(presenceField("speaking", 0, false).mood, "speaking");
  assert.equal(presenceCaption("listening"), "I'm listening");
  const calm = presenceField("waiting", 0, false);
  const stirred = blendField(calm, presenceField("speaking", 0.4, false), 0.5);
  assert.ok(stirred.energy > calm.energy);
  assert.equal(stirred.mood, "speaking");
});
