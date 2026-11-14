import { useEffect } from "react";
import { Link } from "react-router-dom";
import { Contrast, Sparkle } from "lucide-react";
import { Hero, PipAvatar } from "@/components/illustrations";
import ProductMark from "@/layout/ProductMark";
import { BOT_NAME } from "@/lib/people";
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
    <figure className="m-0 rounded-card border border-border bg-sheet p-5 shadow-card sm:p-6" aria-label="Example conversation">
      <div className="mb-3 flex items-center gap-2 text-sm text-muted-fg">
        <span
          className="inline-flex h-6 items-center gap-1.5 rounded-full pr-2.5 pl-2 font-bold"
          style={{ background: "var(--status-new-bg)", color: "var(--status-new-fg)" }}
        >
          <Sparkle aria-hidden="true" className="size-3.5" strokeWidth={2} />
          New
        </span>
        Example chat
      </div>
      <div className="border-b border-border pb-3">
        <p className="m-0 text-sm font-bold">You</p>
        <p className="m-0 mt-1">I changed my email address but I still get messages at the old one.</p>
      </div>
      <div className="my-3 rounded-2xl bg-bot px-4 py-3.5">
        <p className="m-0 flex flex-wrap items-center gap-2 text-sm">
          <PipAvatar className="size-7" />
          <span className="font-bold">{BOT_NAME}</span>
          <span className="rounded-full bg-sheet px-2 py-0.5 text-xs font-bold text-muted-fg">AI assistant</span>
        </p>
        <p className="m-0 mt-1.5">
          A new address only takes effect once you confirm it. Look for the confirmation message in the new inbox and
          open its link.
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm text-muted-fg">
        <span
          className="inline-flex h-6 items-center gap-1.5 rounded-full pr-2.5 pl-2 font-bold"
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
    <section className="rounded-card border border-border bg-sheet p-6 shadow-card md:p-8">
      <h2 className="m-0 mb-4 text-xl">{title}</h2>
      <ol className="m-0 flex list-decimal flex-col gap-2 pl-5 text-muted-fg marker:text-muted-fg">
        {steps.map(([lead, rest]) => (
          <li key={lead}>
            <span className="font-bold text-fg">{lead}</span> {rest}
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
      <div className="flex min-h-dvh flex-col bg-frame text-fg">
        <header className="flex h-16 items-center gap-3 px-4 md:px-10">
          <ProductMark />
          <span className="truncate font-display text-md font-bold">{brand}</span>
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
          <div className="mx-auto max-w-6xl px-4 pt-4 md:px-10">
            <div className="grid items-center gap-8 rounded-[28px] bg-hero p-7 text-hero-fg md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] md:gap-10 md:p-12">
              <div>
                <h1 className="m-0 max-w-[16ch] text-4xl leading-[1.08] md:text-5xl">
                  Answers for {name || "the product"}, and a person when you need one.
                </h1>
                <p className="m-0 mt-5 max-w-[46ch] text-lg text-[#D5E6DB]">
                  Ask {BOT_NAME}, our AI assistant, and get an answer from the approved help guides. If it needs a person,
                  the conversation becomes a ticket and the support team picks it up where it left off.
                </p>
                <div className="mt-7 flex flex-wrap gap-3">
                  <Button asChild size="lg" className="bg-accent text-hero hover:bg-accent/90 border-accent">
                    <Link to="/login">Sign in</Link>
                  </Button>
                  <Button asChild size="lg" variant="ghost" className="border-hero-soft bg-hero-soft text-hero-fg hover:bg-hero-soft/80">
                    <Link to="/incidents">Check past incidents</Link>
                  </Button>
                </div>
              </div>
              <Hero className="block h-auto w-full max-w-[30rem] justify-self-center" />
            </div>
          </div>

          <div className="mx-auto max-w-6xl px-4 py-8 md:px-10 md:py-12">
            <Example />
          </div>

          <div className="mx-auto grid max-w-6xl gap-6 px-4 pb-14 md:grid-cols-2 md:px-10">
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
