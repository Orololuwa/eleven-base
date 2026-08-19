# Eleven — Authentication System Design Spec

**Companion to:** PRD Feature 0.1 (Authentication)
**Stack:** FastAPI (backend) · React Native (mobile) · Auth0 (identity)
**Status:** Draft v3

---

## 1. Scope

This spec covers authentication and identity only — Feature 0.1 from the M0 PRD. It does not cover session tracking, profile fields beyond identity, or any other M0 feature.

---

## 2. Architecture overview

```
┌────────────────────────┐
│   React Native app      │
│   (iOS / Android)       │
└────────────┬────────────┘
             │ 1. Sign in — Google / Apple / Email OTP
             ▼
┌────────────────────────┐
│          Auth0           │
│  Google · Apple · Email  │
│      (passwordless)      │
└────────────┬────────────┘
             │ 2. Signed JWT (auth0_sub, email, provider)
             ▼
┌────────────────────────┐
│   React Native app       │
│   stores JWT + refresh   │
│   token in Keychain /    │
│   Keystore               │
└────────────┬────────────┘
             │ 3. Bearer JWT on every API call
             ▼
┌──────────────────────────────┐
│        FastAPI backend         │
│  ┌────────────────────────┐  │
│  │ JWT verification (JWKS)  │  │  4. verify signature,
│  └────────────┬────────────┘  │     aud, iss, exp
│  ┌────────────▼────────────┐  │
│  │  Identity resolution      │  │  5. resolve auth0_sub → user
│  │       (see §4)            │  │
│  └────────────┬────────────┘  │
└───────────────┼───────────────┘
                ▼
     ┌────────────────────────┐
     │       PostgreSQL          │
     │  users · user_identities  │
     └────────────────────────┘
```

---

## 3. Connections

Three Auth0 connections, freely combinable — no restrictions on which methods a single account can use:

| Method | Type | Notes |
|---|---|---|
| Google | Social | Standard OAuth client, no extra cost |
| Apple | Social | Requires Apple Developer Program ($99/yr, needed for iOS anyway); mandatory once Google is offered, per App Store review guidelines |
| Email | Passwordless (OTP code) | No password, no password reset flow |

A person can sign up with Google, later add Apple, later add email OTP — all landing on the same account, same session history. No method is exclusive with another, and no one gets permanently locked into whichever method they used first.

---

## 4. Identity resolution

The backend separates "identity" (an `auth0_sub`) from "user" (one account, one history). Behavior depends on which provider is signing in.

**Google or Email — auto-merge applies.** On every authenticated request:

```
┌────────────────────────┐
│ Request arrives with     │
│ JWT (auth0_sub, email)   │
└────────────┬────────────┘
             ▼
┌────────────────────────┐
│ auth0_sub already         │
│ linked to a user?         │
└────────────┬────────────┘
      yes │        │ no
   ┌──────┘        └──────┐
   ▼                       ▼
┌───────────────┐  ┌────────────────────────┐
│ Signed in as     │  │ Email matches an          │
│ existing user    │  │ existing user?            │
└───────────────┘  └────────────┬────────────┘
                          no │        │ yes
                    ┌────────┘        └────────┐
                    ▼                           ▼
        ┌────────────────────────┐  ┌────────────────────────┐
        │ Create new user +         │  │ Attach identity to         │
        │ identity — signed in      │  │ existing user — signed in  │
        └────────────────────────┘  └────────────────────────┘
```

**Apple — no auto-merge, ever.** A fresh Apple sign-in either resolves an already-linked `auth0_sub`, or creates a brand-new account — regardless of what email Apple returns, real or a private-relay address. The email is never used to attempt a match. The only way an Apple identity joins an existing account is explicit in-app linking (below), while the person is already signed in.

**Why exclude Apple specifically:** Google and passwordless email are unconditionally reliable — the email they return is always real and verifiable, so matching on it is safe every time. Apple is the only connection where that isn't guaranteed, since the user chooses "Share My Email" or "Hide My Email" on Apple's own sign-in sheet, outside the app's control. Rather than build conditional behavior that's correct sometimes and wrong other times depending on a choice made outside the app, the predictable rule is simpler: Apple never auto-merges, full stop. The trade-off is a small amount of avoidable friction for Apple users who would have shared a matching real email anyway — accepted for the sake of consistent, debuggable behavior.

**Mitigation: in-app account linking.** A "Sign-in methods" screen in account settings lets a signed-in user add another provider (Google, Apple, or email) to their current account. Because the user is already authenticated when they do this, the new `auth0_sub` is attached directly to their existing `user_id` — no email matching involved, so this is the only path by which Apple joins an existing account, and it works identically whether Apple's email is real or hidden. Apple's relay address is stable per app/user, not regenerated each sign-in — once linked, that identity keeps resolving correctly on every future sign-in. Worth a light one-time nudge after first sign-up ("add a backup sign-in method, in case you switch phones") to get people linking proactively.

---

## 5. Token & session flow

**Mobile:**
1. App triggers Auth0 (native Google/Apple SDK, or the passwordless OTP screen) via the Auth0 RN SDK
2. Auth0 returns a signed JWT (RS256) + refresh token
3. Tokens stored in Keychain (iOS) / Keystore (Android)
4. Every API call attaches the JWT as a `Bearer` header
5. Refresh token is used to silently renew the session — this is what satisfies "session persists across app restarts"

**Backend (FastAPI):**
1. A dependency fetches Auth0's public keys from the JWKS endpoint (cached, periodically refreshed)
2. Verifies signature, `aud`, `iss`, `exp` on every protected request
3. Runs the identity resolution logic in §4 to determine the associated user

---

## 6. Data model (auth-relevant fields only)

```
users
  id               uuid PK
  email            text
  email_verified   boolean
  created_at       timestamptz
  updated_at       timestamptz

user_identities
  id               uuid PK
  user_id          uuid FK -> users
  auth0_sub        text, unique, not null
  provider         enum(google, apple, email)
  created_at       timestamptz
```

`auth0_sub` lives on `user_identities`, not `users` — a single user can accumulate any number of identities over time, in any combination of providers. Profile fields (position, foot, height, etc.) belong to Feature 0.2 and aren't part of this spec.

---

## 7. API surface (auth-relevant only)

| Method | Route | Purpose |
|---|---|---|
| GET | `/me` | Resolve the incoming `auth0_sub` to a user per §4 — existing identity, merge, or create |
| POST | `/me/link` | While authenticated, attach a newly-authenticated `auth0_sub` from a second provider to the current user (§4 mitigation) |

All other endpoints across the app depend on the same Bearer-JWT-verification dependency described in §5.

---

## 8. Non-functional requirements (from PRD 0.1)

| Requirement | Target |
|---|---|
| Account creation | < 20 seconds |
| Path to Start Session | ≤ 2 screens from first open |
| Session persistence | Survives app restart, no re-login |
| Password reset | N/A — no passwords exist in this design |

---

## 9. Open questions / risks

- **Apple users who share their real email** — they won't auto-merge either, even though the email would technically have matched. Accepted trade-off for predictable, provider-independent behavior (see §4); no further action needed.
- **OTP email deliverability at scale** — Auth0's default sender isn't production-grade; a transactional provider (e.g. SendGrid, Postmark) needs to be selected before launch
