import { useEffect, useId, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { CircleAlert, Clock, Eye, EyeOff } from "lucide-react";
import { api, HOME_FOR_ROLE, saveSession } from "../api";
import ProductMark from "@/layout/ProductMark";
import ThemeMenu from "@/layout/ThemeMenu";
import { Button } from "@/ui/button";
import { Input } from "@/ui/input";
import { TooltipProvider } from "@/ui/tooltip";
import { cn } from "@/lib/utils";
import { productName } from "@/utils/product";

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
      <label htmlFor={id} className="text-sm font-medium text-fg">
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
  return (
    <TooltipProvider delayDuration={300}>
      <div className="grid min-h-dvh bg-sheet text-fg md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <aside className="hidden flex-col justify-between border-r border-border bg-frame p-10 md:flex">
          <Link to="/" className="flex items-center gap-2.5 text-fg no-underline">
            <ProductMark />
            <span className="font-semibold">{product ? `${product} support` : "Help desk"}</span>
          </Link>
          <div className="max-w-[40ch]">
            <p className="m-0 text-xl leading-snug font-medium">
              {isSignup ? "An account keeps your chats and tickets in one place." : "One sign-in for customers and the support team."}
            </p>
            <p className="m-0 mt-2 text-muted-fg">
              {isSignup
                ? "Use the email you want replies sent to. Support staff get their accounts from the administrator."
                : "You land on your own page: your tickets and chats, your queue, or the admin console."}
            </p>
          </div>
          <span className="text-sm text-muted-fg">Runs on Sahayak</span>
        </aside>

        <main className="flex flex-col">
          <div className="flex h-14 items-center justify-between px-4 md:justify-end md:px-6">
            <Link to="/" className="flex items-center gap-2 text-fg no-underline md:hidden">
              <ProductMark />
              <span className="font-semibold">{product ? `${product} support` : "Help desk"}</span>
            </Link>
            <ThemeMenu />
          </div>
          <div className="flex flex-1 items-center justify-center px-4 pb-16">
            <form className="flex w-full max-w-[24rem] flex-col gap-4" onSubmit={handleSubmit} noValidate={false}>
              <div>
                <h1 className="m-0 text-2xl font-semibold tracking-tight">{isSignup ? "Create an account" : "Sign in"}</h1>
                <p className="m-0 mt-1.5 text-muted-fg">
                  {isSignup ? (
                    <>
                      Already have one? <Link to="/login">Sign in</Link>
                    </>
                  ) : (
                    <>
                      New here? <Link to="/signup">Create an account</Link>
                    </>
                  )}
                </p>
              </div>

              {wait > 0 && (
                <div role="status" className="flex items-start gap-2 rounded-lg bg-pill-warning px-3 py-2.5 text-sm text-pill-warning-fg">
                  <Clock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
                  <span>
                    Too many attempts. Try again in <span className="font-semibold tabular-nums">{clock(wait)}</span>.
                  </span>
                </div>
              )}
              {error && isSignup && (
                <div role="alert" className="flex items-start gap-2 rounded-lg bg-pill-negative px-3 py-2.5 text-sm text-pill-negative-fg">
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
                    className="h-10"
                  />
                </Field>
              )}
              <Field id={ids.email} label="Email">
                <Input
                  id={ids.email}
                  type="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  maxLength={254}
                  required
                  aria-invalid={credentialsError ? true : undefined}
                  className="h-10"
                />
              </Field>
              <Field id={ids.password} label="Password" error={credentialsError}>
                <div className="relative">
                  <Input
                    id={ids.password}
                    type={showPassword ? "text" : "password"}
                    autoComplete={isSignup ? "new-password" : "current-password"}
                    minLength={isSignup ? 8 : undefined}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    aria-invalid={credentialsError ? true : undefined}
                    aria-describedby={credentialsError ? `${ids.password}-error` : undefined}
                    className={cn("h-10 pr-20", credentialsError && "border-negative")}
                  />
                  <button
                    type="button"
                    onClick={() => setShowPassword((v) => !v)}
                    aria-pressed={showPassword}
                    aria-controls={ids.password}
                    className="absolute inset-y-1 right-1 inline-flex cursor-pointer items-center gap-1.5 rounded-md border-0 bg-transparent px-2 text-sm text-fg shadow-none hover:bg-active focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
                  >
                    {showPassword ? <EyeOff aria-hidden="true" className="size-4" /> : <Eye aria-hidden="true" className="size-4" />}
                    {showPassword ? "Hide" : "Show"}
                  </button>
                </div>
                {isSignup && <p className="m-0 text-sm text-muted-fg">At least 8 characters.</p>}
              </Field>

              <Button type="submit" size="lg" className="mt-1 w-full" disabled={submitting || wait > 0}>
                {submitting ? (isSignup ? "Creating your account…" : "Signing in…") : isSignup ? "Create account" : "Sign in"}
              </Button>
              {!isSignup && (
                <p className="m-0 text-sm text-muted-fg">
                  Staff accounts are created by your administrator. <Link to="/incidents">Incident history</Link>
                </p>
              )}
            </form>
          </div>
        </main>
      </div>
    </TooltipProvider>
  );
}
