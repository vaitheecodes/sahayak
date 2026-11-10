import i18n from '../../src/i18n';
import { ApiError } from '../../src/api/errors';
import { errorMessage } from '../../src/lib/errorMessage';

const t = i18n.t.bind(i18n);

describe('errorMessage', () => {
  it('counts down a rate limit with the right plural', () => {
    const e = new ApiError('rate_limited', { status: 429, retryAfterSeconds: 30 });
    expect(errorMessage(t, e)).toBe("You're going a bit fast. Please try again in 30 seconds.");
    expect(errorMessage(t, e, 1)).toBe("You're going a bit fast. Please try again in 1 second.");
    expect(errorMessage(t, e, 0)).toBe('You can try again now.');
  });

  it('spells out field problems from a 422', () => {
    const e = new ApiError('validation', {
      status: 422,
      fieldErrors: [
        { field: 'description', type: 'string_too_long', max: 8000, message: '' },
        { field: 'subject', type: 'missing', message: '' },
      ],
    });
    expect(errorMessage(t, e)).toBe('Description is too long (at most 8000 characters).\nSubject is required.');
  });

  it("shows the server's own sentence for 400 and 413", () => {
    expect(errorMessage(t, new ApiError('bad_request', { detail: 'At most 5 attachments per message' }))).toBe(
      'At most 5 attachments per message',
    );
    expect(errorMessage(t, new ApiError('too_large', { detail: 'photo.jpg is larger than 10 MB' }))).toBe(
      'photo.jpg is larger than 10 MB',
    );
  });

  it('never shows raw server text for 5xx', () => {
    expect(errorMessage(t, new ApiError('server', { detail: 'Traceback…' }))).toBe(
      'Something went wrong on our side. Please try again.',
    );
  });

  it('has a fallback for non-API errors', () => {
    expect(errorMessage(t, new Error('boom'))).toBe('Something went wrong. Please try again.');
  });

  it('never shows developer text from the server', () => {
    expect(errorMessage(t, new ApiError('bad_request', { detail: 'message cannot be empty' }))).toBe(
      'Something went wrong. Please try again.',
    );
    expect(errorMessage(t, new ApiError('too_large', { detail: 'Content-Length required for uploads' }))).toBe(
      'That upload is too large.',
    );
    expect(errorMessage(t, new ApiError('forbidden', { detail: 'Customer role required' }))).toBe(
      "You don't have access to that.",
    );
    expect(errorMessage(t, new ApiError('not_found', { detail: 'Ticket not found' }))).toBe(
      "We couldn't find that. It may have been removed.",
    );
    expect(errorMessage(t, new TypeError("Cannot read properties of undefined (reading 'x')"))).toBe(
      'Something went wrong. Please try again.',
    );
    expect(errorMessage(t, new ApiError('conflict', { detail: 'Only resolved tickets can be reopened' }))).toBe(
      'Only resolved tickets can be reopened',
    );
  });
});
