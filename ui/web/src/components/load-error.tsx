import {errorMessage} from '@/api/errors';
import {Alert, AlertDescription, AlertTitle} from '@/components/ui/alert';
import {Button} from '@/components/ui/button';

interface LoadErrorProps {
  /** For example "Couldn't load the feed". */
  title: string;
  error: unknown;
  onRetry(): void;
}

/** A failed request: a plain message (no details) and a Retry button. */
export function LoadError({title, error, onRetry}: LoadErrorProps) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className="flex flex-col items-start gap-2">
        {errorMessage(error)}
        <Button variant="outline" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
