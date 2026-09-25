import {afterEach, describe, expect, it} from 'vitest';

import {prepareMockBackend} from './page-setup';
import {db} from './data/db';
import {activeScenario} from './scenarios';

afterEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState(null, '', '/');
});

describe('prepareMockBackend', () => {
  it('keeps the mock session across a reload, like the refresh cookie', () => {
    prepareMockBackend();
    expect(db.login('trader1', 'demo')).toBeDefined();

    // A reload: fresh db state, same tab storage.
    db.reset();
    prepareMockBackend();

    expect(db.refresh()?.user.username).toBe('trader1');
    db.logout();
    expect(db.refresh()).toBeUndefined();
  });

  it('never stores a token in sessionStorage', () => {
    prepareMockBackend();
    const token = db.login('trader1', 'demo')?.access_token ?? '';
    const stored = Object.values({...window.sessionStorage}).join(' ');
    expect(token).not.toBe('');
    expect(stored).not.toContain(token);
  });

  it('applies ?scenario= from the page URL', () => {
    window.history.replaceState(null, '', '/?scenario=running');
    prepareMockBackend();
    expect(activeScenario()).toBe('running');
  });
});
