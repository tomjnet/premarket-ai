import {Link, useParams} from 'react-router';

/** `/news/:id`: the news detail page. Milestone M4 fills it in. */
export function NewsDetailPage() {
  const {id} = useParams();
  return (
    <section className="mx-auto flex max-w-3xl flex-col gap-2">
      <h1 className="text-2xl font-semibold">News item {id}</h1>
      <p className="text-muted-foreground">
        The detail page arrives in the next milestone.
      </p>
      <p>
        <Link to="/news" className="font-medium underline underline-offset-4">
          Back to the news feed
        </Link>
      </p>
    </section>
  );
}
