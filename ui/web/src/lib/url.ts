/** A vendor URL that is safe to render as a link. */
export interface SafeLink {
  href: string;
  /** The host the link really opens (punycode for IDN hosts). */
  hostname: string;
}

/**
 * The link for `url` if it is an absolute `http:` or `https:` URL, otherwise
 * undefined. Vendor URLs are untrusted: `javascript:`, `data:` or relative
 * values must never become links.
 */
export function safeHttpUrl(url: string): SafeLink | undefined {
  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    return undefined;
  }
  if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
    return undefined;
  }
  return {href: parsed.href, hostname: parsed.hostname};
}
