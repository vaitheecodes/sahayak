/* Component gallery — dev route at /ui.
 *
 * Every shared component in every state, on the real page surface, with real
 * Help desk content taken from actual pipeline output rather than lorem. This
 * is how the component layer gets reviewed before it is applied across the
 * three portals, and it stays afterwards as the place to check a change
 * without clicking through three logins.
 */

import { useState } from "react";
import Button from "../components/ui/Button";
import { Input, Textarea, Select } from "../components/ui/Field";
import { StatusChip, RouteChip, ConfidenceChip } from "../components/ui/StatusChip";
import ChatMessage from "../components/ui/ChatMessage";
import TicketListItem from "../components/ui/TicketListItem";
import TicketTextDetail from "../components/TicketTextDetail";

const AI_MARKDOWN = `Great question! Here's the difference between the two leave types:

- **Casual leave:** planned time off, applied for ahead of time and approved by your manager.
- **Sick leave:** can be applied for on the day or afterwards, with a note when your policy asks for one.

To apply for either one:

1. Open **Leave → Apply Leave** and pick the leave type.
2. Choose the dates and add a reason if your policy needs one.
3. Click **Submit** so the request reaches your manager.

If you tell me which dates you need, I can say which type fits.`;

const AI_PLAIN =
  "To install the mobile app, download it from the app store for your phone and sign in with your work email. If sign-in fails afterwards, take a screenshot of the error on the screen.";

const NOW = Date.now();
const ago = (mins) => new Date(NOW - mins * 60000).toISOString();

const TICKETS = [
  {
    ticket_id: "TCK-8f21ab40",
    status: "resolved",
    route: "ai",
    category: "USAGE",
    confidence: 0.97,
    created_at: ago(4),
    ticket_text: "I want you to help me with leave",
  },
  {
    ticket_id: "TCK-1c93de77",
    status: "pending_customer",
    route: "clarify",
    category: "OTHER",
    confidence: 0.42,
    created_at: ago(38),
    ticket_text: "I want to track order 12345",
  },
  {
    ticket_id: "TCK-5a0b2e19",
    status: "open",
    route: "human",
    category: "ACCOUNT",
    confidence: 0.9,
    created_at: ago(190),
    ticket_text:
      "can you show me my current invoice and what plan I am on\n\n--- Escalated after chat ---\nThe customer wants to see their current invoice and know which subscription plan they are on. No order numbers, dates or amounts were mentioned. The AI agent cannot access account details directly and advised the customer to log in. A human agent is needed to provide direct assistance with invoice and plan details.",
  },
  {
    ticket_id: "TCK-27be44c1",
    status: "closed",
    route: "ai",
    category: "SETUP",
    confidence: 0.99,
    created_at: ago(2880),
    ticket_text: "how do I install the mobile app on Android",
  },
];

function Section({ title, note, children }) {
  return (
    <section className="gallery-section">
      <div className="gallery-section-head">
        <h2>{title}</h2>
        {note && <p>{note}</p>}
      </div>
      {children}
    </section>
  );
}

function Swatch({ name, token }) {
  return (
    <div className="swatch">
      <div className="swatch-chip" style={{ background: `var(${token})` }} />
      <span className="swatch-name mono">{name}</span>
    </div>
  );
}

export default function UiGallery() {
  const [expanded, setExpanded] = useState("TCK-5a0b2e19");
  const [loading, setLoading] = useState(false);
  const [draft, setDraft] = useState("");

  return (
    <div className="page wide">
      <header className="gallery-header">
        <h1>Component gallery</h1>
        <p>
          Shared components for the Customer, Agent and Admin portals. Real
          pipeline content, every state.
        </p>
      </header>

      <Section
        title="Surfaces"
        note="One cool near-black, four rungs. A field sits below its card, not on top of it."
      >
        <div className="swatch-row">
          <Swatch name="--surface-page" token="--surface-page" />
          <Swatch name="--surface-raised" token="--surface-raised" />
          <Swatch name="--surface-overlay" token="--surface-overlay" />
          <Swatch name="--surface-input" token="--surface-input" />
        </div>
      </Section>

      <Section
        title="Accent"
        note="accent-500 is a fill (4.09:1 as text). accent-400 carries accent text and icons."
      >
        <div className="swatch-row">
          <Swatch name="--accent-300" token="--accent-300" />
          <Swatch name="--accent-400" token="--accent-400" />
          <Swatch name="--accent-500" token="--accent-500" />
          <Swatch name="--accent-600" token="--accent-600" />
          <Swatch name="--accent-700" token="--accent-700" />
        </div>
      </Section>

      <Section title="Status vocabulary" note="Learned once, used in all three portals.">
        <div className="gallery-cluster">
          <StatusChip status="resolved" />
          <StatusChip status="pending_customer" />
          <StatusChip status="in_progress" />
          <StatusChip status="open" />
          <StatusChip status="closed" />
        </div>
        <div className="gallery-cluster">
          <RouteChip route="ai" />
          <RouteChip route="clarify" />
          <RouteChip route="human" />
          <ConfidenceChip confidence={0.97} />
          <ConfidenceChip confidence={0.82} />
          <ConfidenceChip confidence={0.41} />
        </div>
      </Section>

      <Section title="Buttons" note="Four variants, two sizes, every state.">
        <div className="gallery-cluster">
          <Button variant="primary">Submit ticket</Button>
          <Button variant="secondary">Assign to me</Button>
          <Button variant="ghost">Cancel</Button>
          <Button variant="danger">Unassign</Button>
        </div>
        <div className="gallery-cluster">
          <Button variant="primary" size="sm">
            Mark resolved
          </Button>
          <Button variant="secondary" size="sm">
            View
          </Button>
          <Button variant="primary" disabled>
            Disabled
          </Button>
          <Button
            variant="primary"
            loading={loading}
            onClick={() => {
              setLoading(true);
              setTimeout(() => setLoading(false), 1600);
            }}
          >
            {loading ? "Classifying" : "Click to load"}
          </Button>
        </div>
      </Section>

      <Section title="Form controls" note="Real labels, focus rings, error and disabled states.">
        <div className="gallery-grid">
          <Input label="Email" type="email" placeholder="you@company.com" />
          <Input
            label="Password"
            type="password"
            defaultValue="wrong"
            error="Invalid email or password"
          />
          <Select label="Channel" defaultValue="chat">
            <option value="chat">Chat</option>
            <option value="email">Email</option>
          </Select>
          <Input label="Disabled" placeholder="Not editable" disabled />
        </div>
        <Textarea
          label="Describe your issue"
          hint="Say which part of the product it is about, and what you were doing."
          placeholder="e.g. Prod-WebServer-01 shows down but the site loads fine"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
        />
      </Section>

      <Section
        title="Ticket rows"
        note="Status, mono id, timestamp, the customer's words, and the AI case summary as its own block. Click a row to expand."
      >
        <ul className="stack">
          {TICKETS.map((t) => (
            <TicketListItem
              key={t.ticket_id}
              ticket={t}
              showClassification
              expanded={expanded === t.ticket_id}
              onToggle={() => setExpanded(expanded === t.ticket_id ? null : t.ticket_id)}
              actions={
                t.status === "open" ? (
                  <Button variant="secondary" size="sm">
                    Assign to me
                  </Button>
                ) : null
              }
            >
              <TicketTextDetail ticketText={t.ticket_text} />
            </TicketListItem>
          ))}
        </ul>
      </Section>

      <Section
        title="Agent view of the same rows"
        note="Without showClassification: agents never see category, route or confidence."
      >
        <ul className="stack">
          <TicketListItem ticket={TICKETS[2]} expanded={false} onToggle={() => {}} />
        </ul>
      </Section>

      <Section
        title="Conversation"
        note="AI replies render as markdown — numbered steps look like steps. System lines are state changes, not speakers."
      >
        <div className="chat">
          <div className="chat-scroll">
            <ChatMessage
              sender="customer"
              message="I want you to help me with leave"
              createdAt={ago(9)}
            />
            <ChatMessage sender="ai" message={AI_PLAIN} createdAt={ago(9)} />
            <ChatMessage sender="customer" message="what is the differnce" createdAt={ago(6)} />
            <ChatMessage sender="ai" message={AI_MARKDOWN} createdAt={ago(5)} />
            <ChatMessage sender="system" message="Ticket marked resolved — conversation closed." />
          </div>
          <div className="chat-closed-note">
            This conversation is closed. Raise a new ticket if you need more help.
          </div>
        </div>
      </Section>

      <Section title="Empty state" note="Teaches the interface instead of saying 'nothing here'.">
        <div className="empty">
          <p className="empty-title">No tickets yet</p>
          <p className="empty-body">
            Raise one from the Raise Ticket tab. The AI answers straightforward
            questions instantly and routes anything sensitive to a human.
          </p>
          <Button variant="primary" size="sm">
            Raise a ticket
          </Button>
        </div>
      </Section>
    </div>
  );
}
