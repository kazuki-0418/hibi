// Catch-all handler that delegates every /api/auth/** request to Better Auth.
// Better Auth's own router decides what `/sign-in/...`, `/sign-out`,
// `/callback/{provider}`, etc. mean — the Astro side just wires the verbs
// in and out.
//
// `prerender = false` is required: this endpoint is SSR on Cloudflare Pages
// Functions, not part of the static build. Without it Astro tries to render
// at build time and the auth handler never reaches the runtime.

import type { APIRoute } from "astro";
import { auth } from "../../../lib/auth";

export const prerender = false;

export const ALL: APIRoute = ({ request }) => auth.handler(request);
