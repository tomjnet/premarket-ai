import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';

import {App} from '@/app/app';
import {MockStartError} from '@/app/mock-start-error';

import './index.css';

/** Returns false when mock mode is on but the mock backend failed to start. */
async function startMockBackend(): Promise<boolean> {
  // Read import.meta.env inline, not through a helper: Vite replaces it with
  // literals at build time, so a production build (DEV is false) drops this
  // branch and never emits the MSW chunk, whatever VITE_API_MODE says.
  if (!import.meta.env.DEV || import.meta.env.VITE_API_MODE !== 'mock') {
    return true;
  }
  try {
    const {prepareMockBackend, worker} = await import('@/mocks/browser');
    prepareMockBackend();
    await worker.start({onUnhandledRequest: 'bypass'});
    return true;
  } catch (error: unknown) {
    console.error('Mock backend (MSW) failed to start:', error);
    return false;
  }
}

async function main(): Promise<void> {
  const container = document.getElementById('root');
  if (container === null) {
    throw new Error('index.html has no #root element');
  }
  const mocksReady = await startMockBackend();
  createRoot(container).render(
    <StrictMode>{mocksReady ? <App /> : <MockStartError />}</StrictMode>,
  );
}

void main();
