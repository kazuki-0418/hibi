// Content Collection schema for editions.
//
// Data flows: Python (scripts/dump_editions_to_json.py) writes one JSON per
// edition to src/content/editions/NNNN.json at build time. Astro reads them
// from here. Astro does NOT touch the production DB directly.
//
// Schema mirrors `editions` table + `articles` joined on `edition_id`:
//   - editions: issue_no, date, standfirst?, daily_title?, sources_scanned?
//   - articles: title, url, summary?, category?, source, source_type?
//
// Nullable fields: standfirst / daily_title come from #53 (not implemented yet,
// so existing editions have them null). sources_scanned starts populating from
// the first cron run after PR #64 — older editions stay null.

import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const editions = defineCollection({
  loader: glob({ pattern: "**/*.json", base: "./src/content/editions" }),
  schema: z.object({
    issue_no: z.number().int().positive(),
    date: z.string(), // ISO date, e.g. "2026-04-18"
    standfirst: z.string().nullable(),
    daily_title: z.string().nullable(),
    sources_scanned: z
      .array(
        z.object({
          name: z.string(),
          kind: z.enum(["YouTube", "RSS"]),
          fetched_count: z.number().int().nonnegative(),
          error: z.string().optional(),
        }),
      )
      .nullable(),
    articles: z.array(
      z.object({
        title: z.string(),
        url: z.string().url(),
        summary: z.string().nullable(),
        category: z.string().nullable(),
        source: z.string(),
        source_type: z.string().nullable(),
      }),
    ),
  }),
});

export const collections = { editions };
