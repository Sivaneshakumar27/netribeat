export const normEmail = (s) => (s || '').trim().toLowerCase();
export const isEmail = (s) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normEmail(s));
export const EMAIL_MSG = 'Enter a valid email address, like name@institute.org';
export const MIN_PASSWORD = 12; // mirrors PASSWORD_MIN_LENGTH; the server is authoritative
