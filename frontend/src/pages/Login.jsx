import { useEffect, useId, useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { CircleAlert, Clock, Eye, EyeOff } from "lucide-react";
import { api, HOME_FOR_ROLE, saveSession } from "../api";
import { Hero } from "@/components/illustrations";
import ProductMark from "@/layout/ProductMark";
import { BOT_NAME } from "@/lib/people";
import ThemeMenu from "@/layout/ThemeMenu";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { TooltipProvider } from "@/ui/tooltip";
import { cn } from "@/lib/utils";
import { productName, signupOpen } from "@/utils/product";

/* One sign-in page for every role (/login), and customer sign-up
 * (/signup). The backend works out who the email belongs to and returns
 * the role; we only pick the portal. Technicians and managers are created
 * by the admin, and the admin account comes from server config.
 *
 * Too many attempts (429) shows a countdown from the Retry-After header;
 * the button stays off until it reaches zero. */

function clock(seconds) {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function Field({ id, label, error, children }) {
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-bold text-fg">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} className="m-0 flex items-start gap-1.5 text-sm text-negative">
          <CircleAlert aria-hidden="true" className="mt-0.5 size-3.5 shrink-0" />
          {error}
        </p>
      )}
    </div>
  );
}

export default function Login({ mode = "login" }) {
  const isSignup = mode === "signup";
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState("");
  const [waitUntil, setWaitUntil] = useState(null);
  const [now, setNow] = useState(() => Date.now());
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const ids = { name: useId(), email: useId(), password: useId() };
  const product = productName();
  const wait = waitUntil ? Math.max(0, Math.ceil((waitUntil - now) / 1000)) : 0;

  useEffect(() => {
    if (!waitUntil) return undefined;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [waitUntil]);

  useEffect(() => {
    document.title = isSignup ? "Create an account" : "Sign in";
  }, [isSignup]);

  // Sign-up closed (admin-created accounts only): /signup goes to sign-in.
  if (isSignup && !signupOpen()) return <Navigate to="/login" replace />;

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const result = isSignup ? await api.customerSignup(name, email, password) : await api.login(email, password);
      saveSession(result.token, result.must_change_password);
      navigate(result.must_change_password ? "/change-password" : HOME_FOR_ROLE[result.role]);
    } catch (err) {
      if (err.status === 429) {
        setNow(Date.now());
        setWaitUntil(Date.now() + (err.retryAfter || 60) * 1000);
      } else {
        setError(err.message);
      }
    } finally {
      setSubmitting(false);
    }
  }

  const credentialsError = error && !isSignup ? error : "";
  const brand = product ? `${product} support` : "Help Desk";
  return (
    <TooltipProvider delayDuration={300}>
      <div className="flex min-h-dvh flex-wrap bg-frame text-fg">
        <aside className="hidden min-w-0 flex-1 basis-[28rem] flex-col justify-between gap-8 bg-hero p-12 text-hero-fg md:flex">
          <div className="flex flex-col gap-7">
            <Link to="/" className="flex items-center gap-3 text-hero-fg no-underline">
              <ProductMark className="size-10" />
              <span className="font-display text-[22px] font-bold">{brand}</span>
            </Link>
            <h2 className="m-0 max-w-[520px] font-display text-[42px] leading-[1.1] font-bold">
              {isSignup ? "One account for your chats and tickets." : "Questions answered. People when you need them."}
            </h2>
            <p className="m-0 max-w-[30rem] text-lg leading-relaxed text-[#D5E6DB]">
              Ask {BOT_NAME}, our AI assistant. {BOT_NAME} answers from our approved help articles and brings in a real
              person when it can't.
            </p>
            <ul className="m-0 flex list-none flex-wrap gap-2.5 p-0">
              {["Answers from approved articles", "A person can take over any time", "Your tickets in one place"].map((t) => (
                <li key={t} className="rounded-full bg-hero-soft px-3.5 py-2 text-sm font-bold">
                  {t}
                </li>
              ))}
            </ul>
          </div>
          <Hero className="block h-auto w-full max-w-[28rem] self-center" />
        </aside>

        <main className="flex min-w-0 flex-1 basis-[26rem] flex-col">
          <div className="flex h-14 items-center justify-between px-4 md:justify-end md:px-6">
            <Link to="/" className="flex items-center gap-2 text-fg no-underline md:hidden">
              <ProductMark />
              <span className="font-display font-bold">{brand}</span>
            </Link>
            <ThemeMenu />
          </div>
          <div className="flex flex-1 items-center justify-center px-4 pb-12">
            <form
              className="flex w-full max-w-[27.5rem] flex-col gap-5 rounded-[28px] border border-border bg-sheet p-7 shadow-card sm:p-10"
              onSubmit={handleSubmit}
            >
              <div className="flex flex-col gap-1.5">
                <h1 className="m-0 text-[30px] leading-tight">{isSignup ? "Create your account" : "Welcome back"}</h1>
                <p className="m-0 text-md text-muted-fg">
                  {isSignup
                    ? `Use the email you want replies sent to. You can chat with ${BOT_NAME} right after.`
                    : `Sign in to see your tickets and chat with ${BOT_NAME}.`}
                </p>
              </div>

              {wait > 0 && (
                <div role="status" className="flex items-start gap-2 rounded-2xl bg-pill-warning px-4 py-3 text-sm text-pill-warning-fg">
                  <Clock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  <span>
                    Too many attempts. Try again in <span className="font-bold tabular-nums">{clock(wait)}</span>.
                  </span>
                </div>
              )}
              {error && isSignup && (
                <div role="alert" className="flex items-start gap-2 rounded-2xl bg-pill-negative px-4 py-3 text-sm text-pill-negative-fg">
                  <CircleAlert aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  <span>{error}</span>
                </div>
              )}

              {isSignup && (
                <Field id={ids.name} label="Name">
                  <Input
                    id={ids.name}
                    autoComplete="name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={120}
                    required
                    className="h-12 rounded-[14px] text-md"
                  />
                </Field>
              )}
              <Field id={ids.email} label="Email">
                <Input
                  id={ids.email}
                  type="email"
                  autoComplete="email"
                  placeholder="you@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={254}
                  required
                  aria-invalid={credentialsError ? true : undefined}
                  className="h-12 rounded-[14px] text-md"
                />
              </Field>
              <Field id={ids.password} label="Password" error={credentialsError}>
                <div className="relative">
                  <Input
                    id={ids.password}
                    type={showPassword ? "text" : "password"}
                    autoComplete={isSignup ? "new-password" : "current-password"}
                    minLength={isSignup ? 8 : undefined}
                    placeholder="Your password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    aria-invalid={credentialsError ? true : undefined}
                    aria-describedby={credentialsError ? `${ids.password}-error` : undefined}
                    className={cn("h-12 rounded-[14px] pr-24 text-md", credentialsError && "border-negative")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-pressed={showPassword}
                    aria-controls={ids.password}
                    className="absolute inset-y-1.5 right-1.5 inline-flex cursor-pointer items-center gap-1.5 rounded-xl border-0 bg-transparent px-3 text-sm font-bold text-fg shadow-none hover:bg-active focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {showPassword ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                {isSignup && <p className="m-0 text-sm text-muted-fg">At least 8 characters.</p>}
              </Field>

              <Button type="submit" size="lg" className="w-full text-[17px]" disabled={submitting || wait > 0}>
                {submitting ? (isSignup ? "Creating your account…" : "Signing in…") : isSignup ? "Create account" : "Sign in"}
              </Button>

              {isSignup ? (
                <p className="m-0 text-center text-sm text-muted-fg">
                  Already have an account? <Link to="/login">Sign in</Link>
                </p>
              ) : signupOpen() ? (
                <>
                  <div className="flex items-center gap-3 text-sm text-muted-fg" aria-hidden="true">
                    <span className="h-px flex-1 bg-border" />
                    New here?
                    <span className="h-px flex-1 bg-border" />
                  </div>
                  <Link
                    to="/signup"
                    className="block rounded-[14px] bg-pill-accent px-5 py-3.5 text-center text-md font-bold text-pill-accent-fg no-underline hover:opacity-90 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    Create an account
                  </Link>
                </>
              ) : (
                <p className="m-0 text-center text-sm text-muted-fg">No account yet? Ask your support team for one.</p>
              )}
              {!isSignup && (
                <p className="m-0 text-sm leading-normal text-muted-fg">
                  Support staff sign in here too. Your role decides what you see. <Link to="/incidents">Incident history</Link>
                </p>
              )}
            </form>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
