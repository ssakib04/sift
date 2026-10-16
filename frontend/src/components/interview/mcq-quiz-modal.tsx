"use client";

import { useEffect, useRef, useState } from "react";

import { buttonClass } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { CandidateQuiz, QuizReviewItem, apiRequest, bearer } from "@/lib/api";

function clock(total: number): string {
  const minutes = Math.floor(total / 60);
  const seconds = total % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

function choiceLabel(options: string[], index: number | null): string {
  if (index === null || options[index] === undefined) {
    return "No answer";
  }
  return options[index];
}

function answerKey(sessionId: string): string {
  return `sift-quiz-answers:${sessionId}`;
}

function storedAnswers(sessionId: string, count: number): (number | null)[] | null {
  const raw = sessionStorage.getItem(answerKey(sessionId));
  if (!raw) {
    return null;
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed) || parsed.length !== count) {
      return null;
    }
    const answers = parsed.map((item) => (item === 0 || item === 1 || item === 2 || item === 3 ? item : null));
    return answers;
  } catch {
    return null;
  }
}

export function McqQuizModal({
  sessionId,
  token,
  onClose,
}: {
  sessionId: string;
  token: string;
  onClose: () => void;
}) {
  const [quiz, setQuiz] = useState<CandidateQuiz | null>(null);
  const [answers, setAnswers] = useState<(number | null)[]>([]);
  const [seconds, setSeconds] = useState(0);
  const [message, setMessage] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [sending, setSending] = useState(false);
  const answersRef = useRef<(number | null)[]>([]);
  const sendingRef = useRef(false);

  useEffect(() => {
    let stop = false;
    async function open() {
      try {
        const next = await apiRequest<CandidateQuiz>(`/api/v1/interview-sessions/${sessionId}/quiz`, {
          method: "POST",
          headers: bearer(token),
        });
        if (stop) {
          return;
        }
        const blank = next.questions.map(() => null);
        if (next.status === "submitted") {
          sessionStorage.removeItem(answerKey(sessionId));
        }
        const restored = next.status === "in_progress" ? storedAnswers(sessionId, next.questions.length) ?? blank : blank;
        answersRef.current = restored;
        setAnswers(restored);
        setSeconds(next.seconds_remaining);
        setQuiz(next);
        setMessage("");
      } catch (error: unknown) {
        if (!stop) {
          setMessage(error instanceof Error ? error.message : "The skill quiz could not be opened.");
        }
      }
    }
    void open();
    return () => {
      stop = true;
    };
  }, [sessionId, token]);

  useEffect(() => {
    if (!quiz || quiz.status !== "in_progress") {
      return;
    }
    const timer = window.setInterval(() => {
      setSeconds((current) => (current > 0 ? current - 1 : 0));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [quiz]);

  useEffect(() => {
    if (!quiz || quiz.status !== "in_progress" || seconds > 0) {
      return;
    }
    void send(true);
  }, [quiz, seconds]);

  function choose(questionIndex: number, optionIndex: number) {
    if (!quiz || quiz.status !== "in_progress" || sending) {
      return;
    }
    const next = answers.map((value, index) => (index === questionIndex ? optionIndex : value));
    answersRef.current = next;
    sessionStorage.setItem(answerKey(sessionId), JSON.stringify(next));
    setAnswers(next);
  }

  async function send(auto: boolean) {
    if (!quiz || quiz.status !== "in_progress" || sendingRef.current) {
      return;
    }
    sendingRef.current = true;
    setSending(true);
    setConfirming(false);
    try {
      const next = await apiRequest<CandidateQuiz>(`/api/v1/interview-sessions/${sessionId}/quiz/submit`, {
        method: "POST",
        headers: { ...bearer(token), "Content-Type": "application/json" },
        body: JSON.stringify({ answers: answersRef.current }),
      });
      sessionStorage.removeItem(answerKey(sessionId));
      setQuiz(next);
      setMessage(auto ? "Time is up. Your answers were submitted." : "");
    } catch (error: unknown) {
      sendingRef.current = false;
      setMessage(error instanceof Error ? error.message : "The skill quiz could not be submitted.");
    } finally {
      setSending(false);
    }
  }

  const review = quiz?.status === "submitted" ? quiz.review : null;

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-night/80 p-4 sm:items-center" role="presentation">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="skill-quiz-title"
        className="max-h-[90vh] w-full max-w-2xl overflow-y-auto"
      >
        <Panel elevated>
          <div className="space-y-5 p-5 sm:p-6">
            <header className="flex items-start justify-between gap-4">
              <div>
                <p className="text-sm text-mist">Skill quiz</p>
                <h2 id="skill-quiz-title" className="font-display text-2xl font-medium text-ivory">
                  {review ? "Answer review" : "Ten questions"}
                </h2>
              </div>
              {quiz && quiz.status === "in_progress" ? (
                <p className="font-display text-2xl text-amber" aria-live="polite">
                  {clock(seconds)}
                </p>
              ) : null}
            </header>
            {message ? <p className="text-sm text-mist">{message}</p> : null}
            {!quiz && !message ? <p className="text-sm text-mist">Preparing the quiz from this role’s checklist.</p> : null}
            {quiz && !review ? (
              <p className="text-sm text-mist">
                Choose one answer for each question. The overall result is saved for the recruiter.
              </p>
            ) : null}
            {quiz && !review
              ? quiz.questions.map((question, questionIndex) => (
                  <fieldset key={question.question_id} className="space-y-2">
                    <legend className="text-sm font-medium text-ivory">
                      {questionIndex + 1}. {question.prompt}
                    </legend>
                    <div className="grid gap-2">
                      {question.options.map((option, optionIndex) => {
                        const selected = answers[questionIndex] === optionIndex;
                        return (
                          <button
                            key={option}
                            type="button"
                            aria-pressed={selected}
                            disabled={sending}
                            onClick={() => choose(questionIndex, optionIndex)}
                            className={`rounded-control border px-3 py-2 text-left text-sm ${
                              selected ? "border-amber bg-amber/10 text-ivory" : "border-ivory/15 text-mist"
                            }`}
                          >
                            {option}
                          </button>
                        );
                      })}
                    </div>
                  </fieldset>
                ))
              : null}
            {review ? <ReviewList items={review} /> : null}
            <div className="flex flex-wrap gap-3">
              {quiz && quiz.status === "in_progress" ? (
                <button type="button" className={buttonClass()} disabled={sending} onClick={() => setConfirming(true)}>
                  Submit answers
                </button>
              ) : null}
              <button type="button" className={buttonClass("secondary")} onClick={onClose}>
                Close
              </button>
            </div>
          </div>
        </Panel>
      </div>
      {confirming ? (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-night/70 p-4" role="presentation">
          <div role="dialog" aria-modal="true" aria-labelledby="submit-quiz-title" className="w-full max-w-md">
            <Panel elevated>
              <div className="space-y-4 p-5">
                <h3 id="submit-quiz-title" className="font-display text-2xl font-medium text-ivory">
                  Submit this quiz?
                </h3>
                <p className="text-sm text-mist">You cannot change these answers after they are sent.</p>
                <div className="flex flex-wrap gap-3">
                  <button type="button" className={buttonClass()} disabled={sending} onClick={() => void send(false)}>
                    Submit
                  </button>
                  <button type="button" className={buttonClass("secondary")} onClick={() => setConfirming(false)}>
                    Keep working
                  </button>
                </div>
              </div>
            </Panel>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ReviewList({ items }: { items: QuizReviewItem[] }) {
  return (
    <ol className="space-y-4">
      {items.map((item, index) => (
        <li key={item.question_id} className="space-y-1 text-sm">
          <p className="font-medium text-ivory">
            {index + 1}. {item.prompt}
          </p>
          <p className="text-mist">Your answer: {choiceLabel(item.options, item.selected_index)}</p>
          <p className="text-ivory">Correct answer: {choiceLabel(item.options, item.correct_index)}</p>
          <p className="text-mist">{item.explanation}</p>
        </li>
      ))}
    </ol>
  );
}
