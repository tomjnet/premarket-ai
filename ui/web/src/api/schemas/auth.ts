import {z} from 'zod';

/** Roles known to the UI. ANALYST sees the same pages as TRADER for now. */
export const roleSchema = z.enum(['TRADER', 'ANALYST', 'ADMIN']);

export const authUserSchema = z.object({
  username: z.string().min(1),
  role: roleSchema,
});

/** Wire format of `POST /auth/login` and `POST /auth/refresh` (`200`). */
export const tokenResponseWireSchema = z.object({
  access_token: z.string().min(1),
  token_type: z.literal('bearer'),
  expires_in: z.number().int().positive(),
  user: authUserSchema,
});

/** The login/refresh response as the UI uses it. */
export const authSessionSchema = tokenResponseWireSchema.transform(wire => ({
  accessToken: wire.access_token,
  expiresInS: wire.expires_in,
  user: wire.user,
}));

export type Role = z.infer<typeof roleSchema>;
export type AuthUser = z.infer<typeof authUserSchema>;
export type AuthSession = z.output<typeof authSessionSchema>;
export type TokenResponseWire = z.input<typeof tokenResponseWireSchema>;
