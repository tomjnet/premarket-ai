import {useState} from 'react';

import {Button} from '@/components/ui/button';

const TOOLCHAIN = [
  'Vite + React + TypeScript (strict)',
  'Tailwind CSS + shadcn/ui',
  'Vitest + Testing Library + vitest-axe',
  'MSW mock backend',
  'gts (Google TypeScript style)',
] as const;

/**
 * Placeholder page for milestone M0: proves the toolchain end to end. The
 * real app shell (M2) replaces it.
 */
export function App() {
  const [showToolchain, setShowToolchain] = useState(false);
  const apiMode = import.meta.env.VITE_API_MODE ?? 'live';

  return (
    <>
      <div className="bg-amber-300 px-4 py-1 text-center text-sm font-semibold text-black">
        SIMULATION: synthetic vendor data
      </div>
      <main className="mx-auto flex max-w-2xl flex-col gap-4 p-6">
        <h1 className="text-2xl font-semibold">premarket-ai</h1>
        <p className="text-muted-foreground">
          Decision support only, not investment advice.
        </p>
        <p>
          Scaffold ready. API mode: <strong>{apiMode}</strong>
        </p>
        <div>
          <Button
            aria-expanded={showToolchain}
            aria-controls="toolchain"
            onClick={() => setShowToolchain(shown => !shown)}
          >
            {showToolchain ? 'Hide toolchain' : 'Show toolchain'}
          </Button>
        </div>
        {showToolchain && (
          <ul id="toolchain" className="list-disc pl-6">
            {TOOLCHAIN.map(tool => (
              <li key={tool}>{tool}</li>
            ))}
          </ul>
        )}
      </main>
    </>
  );
}
