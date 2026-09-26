import {useEffect} from 'react';

const APP_NAME = 'premarket-ai';

/**
 * Sets the browser tab title to `<title> · premarket-ai` (WCAG 2.4.2: each
 * page has a title that says what it is). Vendor text is safe here: the
 * document title is plain text.
 */
export function useDocumentTitle(title: string): void {
  useEffect(() => {
    document.title = `${title} · ${APP_NAME}`;
  }, [title]);
}
