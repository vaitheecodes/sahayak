/* A chat turn.
 *
 * Three senders with genuinely different jobs, so they get genuinely
 * different shapes rather than the same rounded rectangle in three colors:
 *
 *   customer  right-aligned, accent fill — the person's own words
 *   ai        left-aligned tinted block with a left rule (not a bubble), named
 *             "Support Bot" and tagged "Automatic reply", markdown-rendered so
 *             numbered steps render as steps instead of "1." typed inline
 *   system    full-width centered rail — not a speaker, a state change
 *             ("escalated to a human", "ticket marked resolved")
 */

import { Bot } from "lucide-react";
import { Markdown } from "../../utils/markdown";
import { BOT_NAME } from "../../lib/people";
import { relativeTime, absoluteTime } from "../../utils/time";

function Avatar({ sender }) {
  if (sender === "customer") return null;
  return (
    <span className="msg-avatar" aria-hidden="true">
      <Bot className="size-4" strokeWidth={1.75} />
    </span>
  );
}

export default function ChatMessage({ sender, message, createdAt, children }) {
  if (sender === "system") {
    return (
      <div className="msg-system">
        <span className="msg-system-rule" aria-hidden="true" />
        <span className="msg-system-text">{message}</span>
        <span className="msg-system-rule" aria-hidden="true" />
      </div>
    );
  }

  const isCustomer = sender === "customer";
  const stamp = createdAt ? relativeTime(createdAt) : "";

  return (
    <div className={`msg msg-${isCustomer ? "customer" : "ai"}`}>
      {!isCustomer && (
        <div className="msg-meta">
          <Avatar sender={sender} />
          <span className="msg-author">{BOT_NAME}</span>
          <span className="msg-tag">Automatic reply</span>
          {stamp && (
            <time className="msg-time" title={absoluteTime(createdAt)}>
              {stamp}
            </time>
          )}
        </div>
      )}
      <div className="msg-body">
        {isCustomer ? <p className="msg-plain">{message}</p> : <Markdown>{message}</Markdown>}
      </div>
      {children}
      {isCustomer && stamp && (
        <time className="msg-time msg-time-right" title={absoluteTime(createdAt)}>
          {stamp}
        </time>
      )}
    </div>
  );
}
