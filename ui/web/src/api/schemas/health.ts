import {z} from 'zod';

/** `GET /health` (`200`). */
export const healthSchema = z.object({status: z.literal('ok')});

export type Health = z.infer<typeof healthSchema>;
