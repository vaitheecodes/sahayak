import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Bot, Contrast, Sparkle } from "lucide-react";
import ProductMark from "@/layout/ProductMark";
import ThemeMenu from "@/layout/ThemeMenu";
import { TooltipProvider } from "@/ui/tooltip";
import { Button } from "@/ui/button";
import { productName, signupOpen } from "@/utils/product";

/* The public front door at / for signed-out visitors: what this help desk
 * does, one way in (sign in), how it works for customers and for the
 * support team. The product's name comes from Settings -> Product; the
 * platform is Sahayak. No testimonials, logos or numbers. */

function Example() {
  // A made-up exchange that shows the hand-off; it names no real product.
  return (
    <figure className="m-0 rounded-2xl border border-border bg-frame p-4 sm:p-5" aria-label="Example conversation">
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-fg">
        <span
          className="inline-flex h-[22px] items-center gap-1.5 rounded-md pr-2 pl-1.5 font-medium"
          style={{ background: "var(--status-new-bg)", color: "var(--status-new-fg)" }}
        >
          <Sparkle aria-hidden="true" className="size-3.5" strokeWidth={2} />
          New
        </span>
        Example chat
      </div>
      <div className="border-b border-border pb-3">
        <p className="m-0 text-sm font-semibold">You</p>
        <p className="m-0 mt-1">I changed my email address but I still get messages at the old one.</p>
      </div>
      <div className="my-3 rounded-r-lg border-l-[3px] border-bot-rule bg-bot px-3.5 py-3">
        <p className="m-0 flex flex-wrap items-center gap-2 text-sm">
          <Bot aria-hidden="true" className="size-4 text-primary" strokeWidth={1.75} />
          <span className="font-semibold">Support Bot</span>
          <span className="rounded border border-border-strong px-1.5 text-xs text-muted-fg">From the help guides</span>
        </p>
        <p className="m-0 mt-1.5">
          A new address only takes effect once you confirm it. Look for the confirmation message in the new inbox and
          open its link.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-fg">
        <span
          className="inline-flex h-[22px] items-center gap-1.5 rounded-md pr-2 pl-1.5 font-medium"
          style={{ background: "var(--status-progress-bg)", color: "var(--status-progress-fg)" }}
        >
          <Contrast aria-hidden="true" className="size-3.5" strokeWidth={2} />
          In progress
        </span>
        Still stuck? It becomes a ticket for the support team, with the chat attached.
      </div>
    </figure>
  );
}

function Steps({ title, steps }) {
  return (
    <section className="border-t border-border pt-5 md:pr-8 [&+&]:md:border-l [&+&]:md:pl-8">
      <h2 className="m-0 mb-3 text-lg font-semibold">{title}</h2>
      <ol className="m-0 flex list-decimal flex-col gap-2 pl-5 text-muted-fg marker:text-muted-fg">
        {steps.map(([lead, rest]) => (
          <li key={lead}>
            <span className="font-medium text-fg">{lead}</span> {rest}
          </li>
        ))}
      </ol>
    </section>
  );
}

export default function Landing() {
  const name = productName();
  const brand = name ? `${name} support` : "Help desk";

  useEffect(() => {
    document.title = brand;
  }, [brand]);

  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-dvh flex-col bg-sheet text-fg">
        <header className="flex h-16 items-center gap-3 px-4 md:px-10">
          <ProductMark />
          <span className="truncate text-base font-semibold">{brand}</span>
          <span className="flex-1" />
          <ThemeMenu />
          {signupOpen() && (
            <Button asChild variant="outline" size="lg" className="hidden sm:inline-flex">
              <Link to="/signup">Create an account</Link>
            </Button>
          )}
          <Button asChild size="lg">
            <Link to="/login">Sign in</Link>
          </Button>
        </header>

        <main className="flex-1">
          <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-10 md:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)] md:gap-14 md:px-10 md:py-16">
            <div>
              <h1 className="m-0 max-w-[16ch] text-4xl leading-[1.08] font-semibold tracking-tight md:text-5xl">
                Answers for {name || "the product"}, and a person when you need one.
              </h1>
              <p className="m-0 mt-5 max-w-[46ch] text-lg text-muted-fg">
                Ask a question and get an answer from the help guides. If it needs a person, the conversation becomes a
                ticket and the support team picks it up where it left off.
              </p>
              <div className="mt-7 flex flex-wrap gap-3">
                <Button asChild size="lg">
                  <Link to="/login">Sign in</Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link to="/incidents">Check past incidents</Link>
                </Button>
              </div>
            </div>
            <Example />
          </div>

          <div className="mx-auto grid max-w-6xl gap-6 px-4 pb-14 md:grid-cols-2 md:gap-0 md:px-10">
            <Steps
              title={name ? `If you use ${name}` : "If you need help"}
              steps={[
                ["Start a chat", "or raise a ticket, with a screenshot if it helps."],
                ["Get an answer", "from the help guides straight away."],
                ["Hand it to a person", "when it needs one. Nothing to repeat."],
              ]}
            />
            <Steps
              title="If you are on the support team"
              steps={[
                ["See your queue:", "what is new, what is yours and what is close to its deadline."],
                ["Pick up a ticket", "with the chat so far and a summary of what was tried."],
                ["Keep the guides current", "by reviewing drafts made from your own documentation."],
              ]}
            />
          </div>
        </main>

        <footer className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border px-4 py-5 text-sm text-muted-fg md:px-10">
          <span>Runs on Sahayak</span>
          <Link to="/incidents" className="text-muted-fg">
            Incident history
          </Link>
          <Link to="/docs/routing-policy" className="text-muted-fg">
            How tickets are routed
          </Link>
        </footer>
      </div>
    </TooltipProvider>
  );
}
