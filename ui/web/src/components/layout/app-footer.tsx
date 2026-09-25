import {useQuery} from '@tanstack/react-query';
import {CircleCheck, CircleX, LoaderCircle} from 'lucide-react';
import {useId, useState} from 'react';

import {getHealth} from '@/api/health';
import {Badge} from '@/components/ui/badge';
import {Button} from '@/components/ui/button';
import {useSession} from '@/features/auth/session-context';
import {ENV} from '@/lib/env';
import {
  SCENARIOS,
  isScenarioName,
  scenarioFromPage,
  scenarioUrl,
} from '@/lib/mock-scenarios';
import type {ScenarioName} from '@/lib/mock-scenarios';
import {tabStorage} from '@/lib/storage';

const HEALTH_POLL_MS = 60_000;

/** Backend status, and in mock mode the MOCK API tag and scenario switcher. */
export function AppFooter() {
  return (
    <footer className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t px-4 py-3 text-sm">
      <HealthStatus />
      {ENV.apiMode === 'mock' && <MockControls />}
    </footer>
  );
}

function HealthStatus() {
  const {client} = useSession();
  const health = useQuery({
    queryKey: ['health'],
    queryFn: ({signal}) => getHealth({client, signal}),
    refetchInterval: HEALTH_POLL_MS,
    retry: false,
  });
  // Text plus icon: the state never depends on color alone.
  let content = (
    <>
      <LoaderCircle aria-hidden="true" className="size-4" />
      Backend: checking…
    </>
  );
  if (health.isSuccess) {
    content = (
      <>
        <CircleCheck
          aria-hidden="true"
          className="size-4 text-green-700 dark:text-green-400"
        />
        Backend: ok
      </>
    );
  } else if (health.isError) {
    content = (
      <>
        <CircleX aria-hidden="true" className="size-4 text-destructive" />
        Backend: unreachable
      </>
    );
  }
  return (
    <p className="flex items-center gap-1.5" aria-live="polite">
      {content}
    </p>
  );
}

function currentScenario(): ScenarioName {
  return scenarioFromPage(window.location.search, tabStorage());
}

/**
 * Mock mode only. "Apply" reloads the page with `?scenario=`; changing the
 * select alone doesn't, so arrow keys can step through the list.
 */
function MockControls() {
  const selectId = useId();
  const [active] = useState(currentScenario);
  const [chosen, setChosen] = useState<ScenarioName>(active);
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={event => {
        event.preventDefault();
        window.location.assign(scenarioUrl(window.location.href, chosen));
      }}
    >
      <Badge variant="outline">MOCK API</Badge>
      <label htmlFor={selectId}>Mock scenario</label>
      <select
        id={selectId}
        value={chosen}
        onChange={event => {
          const name = event.target.value;
          if (isScenarioName(name)) {
            setChosen(name);
          }
        }}
        className="rounded-md border bg-background px-2 py-1"
      >
        {SCENARIOS.map(name => (
          <option key={name} value={name}>
            {name}
          </option>
        ))}
      </select>
      <Button
        type="submit"
        size="sm"
        variant="outline"
        disabled={chosen === active}
      >
        Apply (reloads)
      </Button>
    </form>
  );
}
