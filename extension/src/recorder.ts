import type { BrowserAction, Target } from './types';

const sensitivePattern = /password|passcode|secret|token|api.?key|credit.?card|card.?number|cvv|security.?code|one.?time|otp|auth/i;
const text = (value: string | null | undefined, max = 160) => value?.replace(/\s+/g, ' ').trim().slice(0, max) || undefined;
function sensitive(element: Element): boolean {
  if (!(element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement)) return false;
  const values = [element.type, element.autocomplete, element.name, element.id, element.getAttribute('aria-label'), element.getAttribute('placeholder')];
  return values.some((value) => value && sensitivePattern.test(value));
}
function stableCss(element: Element): string | undefined {
  if (!(element instanceof HTMLElement)) return undefined;
  if (element.id && /^[A-Za-z][\w-]{2,}$/.test(element.id) && !sensitivePattern.test(element.id)) return `#${CSS.escape(element.id)}`;
  const testId = element.getAttribute('data-testid') || element.getAttribute('data-test-id');
  if (testId) return `[data-testid="${CSS.escape(testId)}"]`;
  return undefined;
}
function xpath(element: Element): string | undefined {
  if (!(element instanceof HTMLElement) || element.id) return undefined;
  const parts: string[] = [];
  let current: Element | null = element;
  while (current && current !== document.body && parts.length < 3) {
    let index = 1; let sibling = current.previousElementSibling;
    while (sibling) { if (sibling.tagName === current.tagName) index++; sibling = sibling.previousElementSibling; }
    parts.unshift(`${current.tagName.toLowerCase()}[${index}]`); current = current.parentElement;
  }
  return current === document.body ? `/${parts.join('/')}` : undefined;
}
export function extractTarget(element: Element): Target | undefined {
  if (!(element instanceof HTMLElement)) return undefined;
  const labelled = element.getAttribute('aria-label') || (element as HTMLInputElement).labels?.[0]?.textContent;
  const role = element.getAttribute('role') || ({ BUTTON: 'button', A: 'link', INPUT: (element as HTMLInputElement).type === 'checkbox' ? 'checkbox' : 'textbox', SELECT: 'combobox' } as Record<string, string | undefined>)[element.tagName];
  const target: Target = { tag: element.tagName.toLowerCase(), role, name: text(labelled || element.getAttribute('aria-labelledby')), text: text(element.textContent, 100), label: text((element as HTMLInputElement).labels?.[0]?.textContent), placeholder: text(element.getAttribute('placeholder')), test_id: text(element.getAttribute('data-testid') || element.getAttribute('data-test-id')), css: stableCss(element), xpath: xpath(element) };
  return Object.fromEntries(Object.entries(target).filter(([, value]) => value)) as Target;
}
export function action(type: BrowserAction['type'], element?: Element, value?: string): BrowserAction | undefined {
  if (element && sensitive(element)) return undefined;
  return { type, timestamp: new Date().toISOString(), url: location.href, title: document.title, ...(element ? { target: extractTarget(element) } : {}), ...(value === undefined ? {} : { value }) };
}
export function isSensitive(element: Element) { return sensitive(element); }
