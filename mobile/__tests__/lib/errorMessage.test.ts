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
});
