// Better Auth instance for Hibi's Astro web app.
//
// Schema is owned by migrations/007_better_auth_schema.sql (#103, merged).
// Hibi keeps column names snake_case to match the rest of the database
// (articles, clicks, editions), so every model's camelCase fields are mapped
// to the actual snake_case columns here. The schema side is authoritative —
// do not edit the fields map to make columns appear; add a migration instead.
//
// Database driver is `@neondatabase/serverless` (WebSocket-based) because
// Astro routes that touch auth run on Cloudflare Pages Functions (Workers
// runtime), which cannot use `pg` (depends on node:net).
//
// Magic link send is a phase-1 placeholder: it console.logs the URL.
// Real Gmail delivery lands in #117 alongside the mailer changes.

import { betterAuth } from "better-auth";
import { magicLink } from "better-auth/plugins";
import { Pool } from "@neondatabase/serverless";

const isProd = process.env.NODE_ENV === "production";

export const auth = betterAuth({
  database: new Pool({
    connectionString: process.env.DATABASE_URL,
  }),

  // ---- snake_case field mapping ----------------------------------------
  // Maps Better Auth's camelCase JS field names to the snake_case columns
  // created by migration 007. Must stay in sync with that migration.
  user: {
    fields: {
      emailVerified: "email_verified",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  session: {
    fields: {
      userId: "user_id",
      expiresAt: "expires_at",
      ipAddress: "ip_address",
      userAgent: "user_agent",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  account: {
    fields: {
      userId: "user_id",
      accountId: "account_id",
      providerId: "provider_id",
      accessToken: "access_token",
      refreshToken: "refresh_token",
      accessTokenExpiresAt: "access_token_expires_at",
      refreshTokenExpiresAt: "refresh_token_expires_at",
      idToken: "id_token",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },
  verification: {
    fields: {
      expiresAt: "expires_at",
      createdAt: "created_at",
      updatedAt: "updated_at",
    },
  },

  // ---- auth methods ----------------------------------------------------
  // Hibi intentionally has no password auth — magic link + OAuth only,
  // matching the email-first product surface.
  emailAndPassword: {
    enabled: false,
  },
  plugins: [
    magicLink({
      sendMagicLink: async ({ email, url }) => {
        // #117 will replace this with the Gmail-API path used by mailer.py.
        // Until then the URL is surfaced in server logs so a developer can
        // click through during local smoke tests.
        console.log(`[magic-link] ${email} -> ${url}`);
      },
    }),
  ],
  socialProviders: {
    github: {
      clientId: process.env.GITHUB_CLIENT_ID ?? "",
      clientSecret: process.env.GITHUB_CLIENT_SECRET ?? "",
    },
    google: {
      clientId: process.env.GOOGLE_CLIENT_ID ?? "",
      clientSecret: process.env.GOOGLE_CLIENT_SECRET ?? "",
    },
  },

  // ---- cookies ---------------------------------------------------------
  // Secure cookies only in production so `astro dev` over plain HTTP at
  // localhost still works during development.
  advanced: {
    useSecureCookies: isProd,
  },

  secret: process.env.BETTER_AUTH_SECRET,
});
