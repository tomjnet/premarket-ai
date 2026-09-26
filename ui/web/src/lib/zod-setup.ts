/**
 * @fileoverview Global zod settings. Imported first by `main.tsx` (and the
 * test setup), before any schema is used.
 *
 * `jitless`: zod 4 otherwise probes `new Function` to compile fast parsers.
 * The site's Content-Security-Policy forbids eval (no `'unsafe-eval'`, and
 * Trusted Types), so the probe would only log violations before zod fell
 * back. Parsing about 100 feed items needs no compiler.
 */

import {z} from 'zod';

z.config({jitless: true});
