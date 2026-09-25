import {z} from 'zod';

/** One entry of a FastAPI `422` body. */
export const validationIssueSchema = z.object({
  loc: z.array(z.union([z.string(), z.number()])),
  msg: z.string(),
  type: z.string(),
});

/**
 * FastAPI error body: `{"detail": "..."}` or, for `422`, a list of
 * validation issues. `5xx` bodies can be anything and are not parsed.
 */
export const errorBodySchema = z.object({
  detail: z.union([z.string(), z.array(validationIssueSchema)]),
});

export type ErrorBody = z.infer<typeof errorBodySchema>;
export type ValidationIssue = z.infer<typeof validationIssueSchema>;
