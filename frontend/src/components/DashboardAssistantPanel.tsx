import { useState } from "react";
import { Bot, Send, X } from "lucide-react";
import { useInterpretAssistant } from "@/lib/hooks";
import type { AssistantMetric } from "@/lib/types";

export function DashboardAssistantPanel({
  metrics,
  onClose,
}: {
  metrics: AssistantMetric[];
  onClose: () => void;
}) {
  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState("");
  const assistant = useInterpretAssistant();

  const submit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const prompt = question.trim();
    if (prompt.length < 3 || assistant.isPending) return;
    setAnswer("");
    assistant.mutate(
      { question: prompt, metrics },
      {
        onSuccess: (result) => {
          setAnswer(result.answer);
          setQuestion("");
        },
      },
    );
  };

  return (
    <div
      className="fixed inset-0 z-[1200] bg-ink/25"
      role="presentation"
      onClick={onClose}
    >
      <aside
        aria-labelledby="dashboard-assistant-title"
        aria-modal="true"
        className="absolute inset-y-0 right-0 flex w-full max-w-[26rem] flex-col border-l border-border bg-surface shadow-pop"
        role="dialog"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border px-5 py-4">
          <div className="flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-water-50 text-water-700">
              <Bot size={19} />
            </span>
            <div>
              <h2 id="dashboard-assistant-title" className="text-sm font-semibold text-ink">
                LakeWatch AI
              </h2>
              <p className="text-xs text-muted">Your dashboard, explained</p>
            </div>
          </div>
          <button
            type="button"
            className="btn-ghost h-9 w-9 px-0"
            onClick={onClose}
            aria-label="Close LakeWatch AI"
          >
            <X size={17} />
          </button>
        </header>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-5" aria-live="polite">
          <div className="rounded-lg border border-water-100 bg-water-50/70 p-3 text-xs leading-relaxed text-ink-soft">
            Ask what a metric means or how to read a trend. Only the summary metrics shown on this
            dashboard and your question are sent to the configured AI provider when you submit.
            Raw satellite files and unpublished map layers are not sent.
          </div>
          {!answer && !assistant.isError ? (
            <div className="space-y-2">
              <p className="text-xs font-medium uppercase tracking-wide text-muted">Try asking</p>
              {[
                "What does water extent mean?",
                "How should I read the latest forecast?",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  className="block w-full rounded-md border border-border px-3 py-2 text-left text-sm text-ink-soft hover:bg-canvas"
                  onClick={() => setQuestion(suggestion)}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          ) : null}
          {answer ? (
            <div className="rounded-lg bg-canvas px-4 py-3 text-sm leading-relaxed text-ink-soft">
              {answer}
            </div>
          ) : null}
          {assistant.isError ? (
            <p className="rounded-md border border-danger/30 bg-danger-light px-3 py-2 text-sm text-danger-dark" role="alert">
              {assistant.error instanceof Error
                ? assistant.error.message
                : "The AI assistant could not answer. Please try again."}
            </p>
          ) : null}
        </div>

        <form className="border-t border-border p-4" onSubmit={submit}>
          <label htmlFor="lakewatch-ai-question" className="sr-only">
            Ask about the dashboard metrics
          </label>
          <textarea
            id="lakewatch-ai-question"
            className="input min-h-24 resize-y"
            maxLength={1000}
            placeholder="Ask a question about these metrics…"
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <div className="mt-2 flex items-center justify-between gap-3">
            <span className="text-xs text-muted">Explanations are informational, not advice.</span>
            <button
              type="submit"
              className="btn-primary"
              disabled={question.trim().length < 3 || assistant.isPending}
            >
              <Send size={14} />
              {assistant.isPending ? "Thinking…" : "Ask"}
            </button>
          </div>
        </form>
      </aside>
    </div>
  );
}
