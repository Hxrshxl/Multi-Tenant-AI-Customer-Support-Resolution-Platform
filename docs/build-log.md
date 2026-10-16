# Build Log — What We Built, and Why It Matters

A plain-English record of every Jira card as it is completed. Each entry
answers four questions:

1. **What we built** — in everyday language, no jargon.
2. **Why it matters commercially** — what it saves, prevents, or enables.
3. **The technical bit** — for when you need the real detail.
4. **What it cost** — the honest trade-offs, and what is still missing.

The point of this document is to be able to explain any decision in this
codebase to a non-engineer: a client stakeholder, a hiring manager, or
yourself in six months.

---

## KAN-13 — Repository scaffold and one-command local environment

> **In one sentence:** we set up the workshop before building any furniture.

### What we built

Five things, none of which a customer will ever see:

1. **A one-command start-up.** Anyone can download this project and get the
   whole system — database, cache, application — running on their laptop by
   typing `docker compose up -d`. No multi-page setup guide, no asking a
   colleague which version of Postgres the team uses.

2. **An exact parts list.** Every software library this project uses is
   recorded with its precise version number, including the libraries that
   those libraries themselves depend on. 59 entries in total.

3. **Settings that refuse to start when something is missing.** If the
   database address is absent, the application does not boot. It stops
   immediately and prints exactly which settings are missing.

4. **One command that checks quality.** A single command runs the style
   checker, the type checker and the full test suite. Same behaviour on
   Windows and Linux.

5. **A gatekeeper before code is saved.** Ten automatic checks run every time
   code is committed to history. One of them scans for passwords and API keys.

### Why it matters commercially

**Onboarding is a real cost.** As a forward-deployed engineer, if environment
setup eats two days at every client site, that is two days of billed time
producing nothing a client can see. A one-command setup turns that into
fifteen minutes. The same applies to your own future self, returning to this
project after a month away.

**"Works on my machine" is the most expensive class of bug.** When two people
have different library versions, a bug appears for one and not the other, and
hours vanish into a problem that teaches nothing. An exact parts list means a
bug reproduces identically everywhere, so the debugging is about the bug
rather than the environment.

**The secret scanner is the cheapest security control that exists.** If a
database password is committed to version control, it does not simply get
deleted — it lives in the repository history permanently. The real cost is
rotating every affected credential, auditing what was accessed, and in a
regulated industry, notifying someone. Catching it before it enters history
costs nothing. It already caught a test password during this work.

**Fail-fast settings prevent a specific, nasty failure.** Picture a service
that starts happily with a missing database address, then crashes at 3am on
the first real customer request. Someone is woken to diagnose a mystery. A
service that refuses to start and says "DATABASE_URL is required but was not
set" costs ten seconds instead.

### The technical bit

- **Docker Compose** — a recipe file that starts the database and cache as
  disposable, isolated containers. Delete and recreate them freely; nothing is
  installed on your actual machine.
- **pgvector** — an add-on for the Postgres database that lets it store
  meaning as numbers. This is what will later allow searching a company's
  documentation by meaning rather than by exact keyword. Enabled now so it is
  simply there when retrieval work begins.
- **Lockfile** — the exact parts list. One file holds the libraries we chose
  directly; another holds everything, including dependencies of dependencies.
- **Pre-commit hooks** — small programs that run automatically before a commit
  is recorded, and block it if they fail.
- **Non-root container** — the application runs inside Docker as a restricted
  user, so if it were ever compromised the attacker would not gain
  administrator rights inside that container.

### The one decision worth remembering

We put a `tenant_id` column on every table in the very first database design,
even though the system currently serves only one company.

**Why this matters:** multi-tenant means one running system serving many
customer companies, with each company's data strictly invisible to the others.
If you add that separation later, you must revisit every single database query
in the entire codebase and confirm each one filters correctly. Miss one, and
Company A sees Company B's support tickets — the kind of incident that ends a
contract.

Doing it on day one is nearly free. The analogy: writing the address on each
envelope as you fill it, versus returning to a warehouse of unaddressed mail
and trying to work out where every piece was meant to go.

### What it cost, honestly

- **Nothing visible was delivered.** Zero customer-facing functionality. This
  is pure foundation.
- **The Docker stack has never actually been started.** Docker Desktop was not
  running on the development machine, so the recipe file is verified as
  syntactically correct but has not been proven to work end to end.
- **The sample-data command does nothing yet.** There are no database tables
  to fill until KAN-15. It says so plainly rather than pretending to succeed.

---

## KAN-14 — Service skeleton: tracking numbers, logs, errors, health checks

> **In one sentence:** we gave the system a nervous system before giving it
> muscles.

### What we built

Four capabilities. Again mostly invisible to a customer, but every feature
built from here on inherits all four for free.

**1. A tracking number on every request.**

Every incoming request gets a unique ID, like a parcel tracking number. Every
note the system writes while handling that request carries the same number,
and the number is handed back to whoever made the request.

So when a customer says "something went wrong with my refund around 3pm", you
ask for their reference, search that one number, and see the complete story:
what arrived, what the system decided, which external services it called, and
exactly where it failed.

**2. Machine-readable notes, with passwords automatically blanked out.**

Instead of free-text diary entries, the system writes structured records that
software can search, count and alert on. Any password that would have appeared
is replaced with a redaction marker automatically.

**3. One consistent shape for every failure.**

Every error — a missing ticket, a malformed request, an unexpected crash —
comes back looking identical: a short machine-readable code, a sentence in
English, and the tracking number. Internal detail is never included: no
programming error names, no file paths, no database connection strings.

**4. Two different health questions, answered separately.**

- One endpoint answers "is this process alive?" and checks nothing else.
- Another answers "can this process actually do useful work?" and checks that
  the database and cache are reachable.

### Why it matters commercially

**Tracking numbers turn hours of guessing into minutes of looking.** This is
the highest-leverage thing in the card. Without it, diagnosing a production
problem means reading thousands of unrelated log lines and guessing which
belong together. On a client site, being able to say "here is exactly what
happened to that ticket" within minutes is the difference between being
trusted and being managed.

**Structured notes are what make monitoring possible at all.** Because the
records are machine-readable, you can later build alerts like "tell me when
more than 2% of tickets fail" or "tell me when responses get slower than three
seconds". You cannot do that with free text. Every dashboard and alarm this
product will ever have depends on this foundation.

**Blanking out passwords prevents a real and common breach.** Logs get copied
to third-party monitoring tools, kept for months, and read by far more people
than have database access. A password sitting in a log line is a genuine
exposure, and it is one of the most common ways credentials leak in practice.

**A consistent error shape has three separate commercial benefits:**

- *Faster integration.* A client's developers write one piece of
  error-handling code instead of special-casing each endpoint. For an FDE that
  is delivery speed measured directly in days.
- *Security.* A leaked error trace tells an attacker your software versions and
  your server's folder structure — a free reconnaissance map.
- *Professionalism.* A paying customer never sees a raw driver error. They see
  a sentence in English and a reference number to quote.

**Separating the two health checks prevents self-inflicted outages.** This one
is subtle and important. Automated systems restart containers that report
unhealthy. If "alive" and "can reach the database" were the same question, a
thirty-second database hiccup would cause every healthy copy of the
application to be killed and restarted at once — turning a brief blip into a
real outage. Keeping them separate means a database wobble pauses traffic to a
copy without destroying it.

### The technical bit

- **Layered structure** — the code is split into three levels: the part that
  speaks HTTP, the part that holds business rules, and the part that talks to
  external systems. The HTTP layer contains no business logic at all, so rules
  can be tested without starting a web server and do not get quietly
  duplicated across endpoints.
- **Tracking number in a context variable** — stored somewhere every layer can
  read without passing it down through every function call. Each request gets
  its own isolated copy, so concurrent requests never mix up their numbers.
- **Even the tracking number is treated as untrusted** — a caller may supply
  their own so a trace spans several systems, but we accept it only if it is
  short and uses safe characters. Otherwise a caller could inject fake lines
  into our logs by including a line break, which is a known attack.
- **Health checks run in parallel** — database and cache are checked at the
  same time rather than one after the other, because a health check that takes
  four seconds is useless to the systems depending on it.

### Two real bugs that only live testing caught

Both are worth being able to tell as stories, because they show why testing
matters rather than merely that it matters.

**Bug 1: crashes arrived without a tracking number.**

The automated tests passed. But when the real server was started and called
over the network, unexpected crashes came back without the tracking number —
the exact situation where you most need one.

The cause: the web framework has its own outermost safety net that catches
crashes and writes the response itself, bypassing our code. Our tracking
number was being applied one layer too deep.

**The lesson, and it is a genuine one:** the simulated test client is not the
same as the real server. Some bugs exist only in the gap between them, and
that is precisely the class of bug that reaches production.

**Bug 2: the health check cried wolf on Windows.**

The readiness endpoint reported "database unreachable" when the database was
completely fine. The real cause was an incompatibility between the database
driver and the way Windows handles concurrent work.

**Why this is worse than it sounds:** a false alarm is indistinguishable from a
real outage. An engineer would chase a database problem that does not exist.
Worse, if an alarm is wrong often enough people stop believing it, and then it
fails to fire on the day something genuinely breaks. Alert fatigue is how real
incidents get missed.

Fixed by using a different, platform-neutral approach for the check.

### What it cost, honestly

- **Still nothing a customer can see.** Two cards in, there is no ticket
  resolution, no AI, and no interface.
- **One check was not fully proven.** The card said readiness should be tested
  by literally stopping the cache service. Docker was not running, so it was
  tested against unreachable addresses instead. The behaviour is proven; that
  exact scenario is not.
- **A known problem was deferred, not solved.** The Windows database
  incompatibility was worked around for a health check. When real data access
  arrives in KAN-15 it must be confronted properly, because the workaround
  does not scale to actual queries.

---

## Why there is no user interface yet

A fair question from any stakeholder: two cards in, and there is nothing to
look at?

The honest answer: **the product is the resolution engine; the interface is a
window onto it.** A polished approval screen with nothing behind it shows an
empty list. And there is genuinely nothing for an interface to display until
the system produces approvals, metrics and traces worth displaying.

Building the screen first means guessing what data will exist, then rewriting
it once the real data arrives. That rewrite is the expensive kind of work.

The interface starts at epic 10 of 12 — roughly two-thirds of the way in.

---

## What these two cards did *not* deliver

Being precise about this matters more than claiming progress.

| Not yet built | Which epic covers it |
|---|---|
| Any database tables | E1 (next card, KAN-15) |
| Reading a company's documentation | E2 |
| Any AI, or any ticket resolution | E5 |
| Refunds, order lookups, any real action | E6 |
| Human approval for risky actions | E8 |
| Actual separation between companies' data | E9 |
| Any screen a person can use | E10 |

What they *did* deliver: each of those will be built on a foundation where
problems are traceable, failures are consistent, credentials do not leak, and
setup is not a two-day ordeal.

---

## The sales-conversation version

If a client asked "what have you done so far?", the honest and useful answer:

> We have built the operational foundation. Every request through this system
> carries a tracking number, so any customer complaint can be traced to
> exactly what happened in minutes rather than hours. Every failure returns a
> consistent, safe response, so your developers integrate against one contract
> instead of guessing. Credentials cannot leak into logs or version control,
> because that is checked automatically before any code is saved. And the
> system can tell your infrastructure the difference between "I am starting
> up" and "I am genuinely broken", which is what stops a brief database blip
> becoming an outage.
>
> None of that is visible to an end user. All of it is the reason the visible
> parts will be safe to ship.

---

## Glossary

| Term | Plain meaning |
|---|---|
| **Multi-tenant** | One running system serving many customer companies, each company's data invisible to the others |
| **Container** | A disposable, isolated box holding a program and everything it needs to run |
| **Correlation ID** | A tracking number attached to one request and to every note written about it |
| **Liveness probe** | An endpoint answering "is this process still alive?" |
| **Readiness probe** | An endpoint answering "can this copy handle traffic right now?" |
| **Lockfile** | A record of the exact version of every library, so builds are identical everywhere |
| **Pre-commit hook** | An automatic check that runs before code is saved to history and can block it |
| **pgvector** | A Postgres add-on storing meaning as numbers, enabling search by meaning rather than keyword |
| **Redaction** | Automatically blanking out sensitive values before they are written down |
| **Structured logging** | Writing notes in a machine-readable format so they can be searched and alerted on |
| **ADR** | Architecture Decision Record: a short note recording a significant decision and the options rejected |
