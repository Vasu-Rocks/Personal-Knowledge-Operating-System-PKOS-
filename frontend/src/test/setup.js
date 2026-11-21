import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// jsdom does not implement scrolling.
Element.prototype.scrollIntoView = Element.prototype.scrollIntoView || function scrollIntoView() {};

afterEach(() => {
  cleanup();
  localStorage.clear();
  sessionStorage.clear();
});
