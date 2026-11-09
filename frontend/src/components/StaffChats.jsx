import { useEffect, useId, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { MessagesSquare } from "lucide-react";
import { api, getRole } from "@/api";
import ChatMessage from "@/components/ui/ChatMessage";
import { Alert } from "@/ui/alert";
import { Badge } from "@/ui/badge";
import { Button } from "@/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/ui/card";
import { EmptyState } from "@/ui/empty-state";
import { Input } from "@/ui/input";
import { Skeleton } from "@/ui/skeleton";
import { Tabs, TabsList, TabsTrigger } from "@/ui/tabs";
import { categoryLabel } from "@/utils/categories";
import { absoluteTime, relativeTime } from "@/utils/time";

/* Chats (GET /api/staff/chats): technicians see every AI chat, managers
 * their department's. Left: the sessions; right: the transcript,
 * read-only, with a link to the ticket a chat escalated to. Joining a live
 * chat ("Take this chat") is the next phase: its place is marked. */

const FILTERS = [
  ["active", "With AI now"],
  ["escalated", "Escalated"],
  ["resolved", "Resolved"],
];
const STATUS_TONE = { active: "info", escalated: "warning", resolved: "positive", abandoned: "neutral" };
const STATUS_LABEL = { active: "With AI", escalated: "Escalated", resolved: "Resolved", abandoned: "Abandoned" };

function ticketLink(ticketId) {
  return getRole() === "manager"
    ? `/manager/tickets?open=${encodeURIComponent(ticketId)}`
    : `/technician/tickets?view=open_pending&open=${encodeURIComponent(ticketId)}`;
}

function Transcript({ sessionId }) {
  const [chat, setChat] = useState(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    api
      .staffChat(sessionId)
      .then((c) => current && setChat(c))
      .catch((err) => current && setError(err.message));
    return () => {
      current = false;
    };
  }, [sessionId]);

  if (error) return <Alert tone="negative">{error}</Alert>;
  if (!chat) return <Skeleton className="h-64" />;
  return (
    <Card>
      <CardHeader>
        <div className="min-w-0">
          <CardTitle>{chat.customer_name}</CardTitle>
          <p className="m-0 mt-0.5 text-sm text-muted-fg">
            {chat.category ? `${categoryLabel(chat.category)} · ` : ""}started {absoluteTime(chat.created_at)}
          </p>
        </div>
        <Badge tone={STATUS_TONE[chat.status]} dot>
          {STATUS_LABEL[chat.status] || chat.status}
        </Badge>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {chat.ticket_id && (
          <Alert tone="warning" title={`Escalated to ticket ${chat.ticket_id}`}>
            <Link to={ticketLink(chat.ticket_id)} className="underline underline-offset-4">
              Open the ticket
            </Link>
          </Alert>
        )}
        <div
          className="flex flex-col items-start gap-2 rounded-lg border border-dashed border-border px-4 py-3"
          aria-label="Take this chat (coming next)"
        >
          <p className="m-0 text-sm font-medium text-fg">Take this chat</p>
          <p className="m-0 text-sm text-muted-fg">
            Joining a live chat from here comes in the next phase. Until then the transcript is read-only.
          </p>
          <Button size="sm" variant="outline" disabled>
            Take this chat
          </Button>
        </div>
        <div className="chat-log" aria-label="Transcript">
          {chat.messages.length === 0 && <p className="m-0 text-sm text-muted-fg">No messages yet.</p>}
          {chat.messages.map((m) => (
            <ChatMessage key={m.message_id} sender={m.role} message={m.content} createdAt={m.created_at} />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function StaffChats() {
  const [params, setParams] = useSearchParams();
  const filter = FILTERS.some(([k]) => k === params.get("filter")) ? params.get("filter") : "active";
  const selected = params.get("chat");
  const [q, setQ] = useState("");
  const [chats, setChats] = useState(null);
  const [error, setError] = useState("");
  const searchId = useId();

  useEffect(() => {
    let current = true;
    const timer = setTimeout(() => {
      api
        .staffChats({ filter, q: q.trim() })
        .then((rows) => {
          if (current) {
            setChats(rows);
            setError("");
          }
        })
        .catch((err) => current && setError(err.message));
    }, 200);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [filter, q]);

  function set(changes) {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    setParams(next, { replace: true });
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(18rem,2fr)_minmax(0,3fr)]">
      <div className="flex min-w-0 flex-col gap-3">
        <Tabs value={filter} onValueChange={(v) => set({ filter: v, chat: null })}>
          <TabsList aria-label="Chats">
            {FILTERS.map(([key, label]) => (
              <TabsTrigger key={key} value={key}>
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
        <label htmlFor={searchId} className="sr-only">
          Search chats
        </label>
        <Input id={searchId} type="search" placeholder="Customer or message" value={q} onChange={(e) => setQ(e.target.value)} />
        {error && <Alert tone="negative">{error}</Alert>}
        <Card className="overflow-hidden">
          {!chats && !error && <Skeleton className="m-4 h-24" />}
          {chats && chats.length === 0 && <EmptyState icon={MessagesSquare} title="No chats here" />}
          {chats && chats.length > 0 && (
            <ul className="m-0 list-none p-0">
              {chats.map((c) => (
                <li key={c.session_id} className="border-b border-rule last:border-0">
                  <button
                    type="button"
                    aria-current={selected === c.session_id ? "true" : undefined}
                    onClick={() => set({ chat: c.session_id })}
                    className="flex w-full cursor-pointer flex-col items-stretch gap-0.5 rounded-none border-0 bg-transparent px-4 py-3 text-left text-fg hover:bg-raised aria-[current=true]:bg-active"
                  >
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate font-medium">{c.customer_name}</span>
                      <span className="shrink-0 text-xs text-muted-fg" title={absoluteTime(c.updated_at)}>
                        {relativeTime(c.updated_at)}
                      </span>
                    </span>
                    <span className="truncate text-sm text-muted-fg">{c.first_message}</span>
                    <span className="text-xs text-muted-fg">
                      {c.message_count} message{c.message_count === 1 ? "" : "s"}
                      {c.ticket_id ? ` · ticket ${c.ticket_id}` : ""}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
      <div className="min-w-0">
        {selected ? (
          <Transcript key={selected} sessionId={selected} />
        ) : (
          <Card>
            <EmptyState icon={MessagesSquare} title="Pick a chat">
              The transcript shows here, read-only.
            </EmptyState>
          </Card>
        )}
      </div>
    </div>
  );
}
