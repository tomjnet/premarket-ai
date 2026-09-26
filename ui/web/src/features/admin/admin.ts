import {
  DOMAIN,
  PASSWORD_MAX_CHARS,
  PASSWORD_MIN_CHARS,
  USERNAME,
} from '@/api/schemas/ops';

/**
 * The admin forms' checks, before anything is sent. The backend checks the
 * same rules (and more: a taken name, an admin locking themselves out).
 */

export function usernameProblem(username: string): string | undefined {
  if (!USERNAME.test(username)) {
    return 'A username starts with a lower-case letter and has only a-z, 0-9, ".", "_" or "-" (at most 64).';
  }
  return undefined;
}

export function passwordProblem(password: string): string | undefined {
  if (password.length < PASSWORD_MIN_CHARS) {
    return `A password has at least ${PASSWORD_MIN_CHARS} characters.`;
  }
  if (password.length > PASSWORD_MAX_CHARS) {
    return `A password has at most ${PASSWORD_MAX_CHARS} characters.`;
  }
  return undefined;
}

export function sourceProblem(
  domain: string,
  reputation: string,
): string | undefined {
  if (domain.length > 253 || !DOMAIN.test(domain)) {
    return 'Enter a domain such as example.com (lower case).';
  }
  const score = Number(reputation);
  if (reputation.trim() === '' || !Number.isFinite(score)) {
    return 'The score is a number from 0 to 1.';
  }
  if (score < 0 || score > 1) {
    return 'The score is a number from 0 to 1.';
  }
  return undefined;
}
