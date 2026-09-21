import { action, isSensitive } from './recorder';
import type { RuntimeMessage } from './types';
let recording = false;
const emit = (event: RuntimeMessage) => chrome.runtime.sendMessage(event).catch(() => undefined);
function capture(type: Parameters<typeof action>[0], element?: Element, value?: string) { const event = action(type, element, value); if (recording && event) emit({ type: 'ACTION', action: event }); }
const INTERACTIVE_ROLES = new Set(['button','link','menuitem','menuitemcheckbox','menuitemradio','option','tab','checkbox','radio','switch','textbox','searchbox','combobox','slider','spinbutton']);
const INTERACTIVE_TAGS = new Set(['BUTTON','A','INPUT','SELECT','TEXTAREA']);
function isInteractive(el: Element | null): boolean {
  if (!el) return false;
  if (INTERACTIVE_TAGS.has(el.tagName)) return true;
  const role = el.getAttribute('role');
  if (role && INTERACTIVE_ROLES.has(role.toLowerCase())) return true;
  if (el.hasAttribute('tabindex') && el.getAttribute('tabindex') !== '-1') return true;
  return false;
}
document.addEventListener('click', (event) => {
  if (!recording) return;
  const el = event.target as Element | null;
  const meaningful = el?.closest('button,a,input,select,textarea,[role="button"],[role="link"],[role="tab"],[role="menuitem"]');
  const candidate = meaningful || (isInteractive(el) ? el : null);
  if (!candidate) return;
  capture('click', candidate);
}, true);
document.addEventListener('input', (event) => { const element = event.target as HTMLInputElement | HTMLTextAreaElement; if (!recording || !element || isSensitive(element)) return; capture('type', element, element.value); }, true);
document.addEventListener('change', (event) => { const element = event.target as HTMLSelectElement | HTMLInputElement; if (!recording || !element || isSensitive(element)) return; if (element instanceof HTMLSelectElement) capture('select', element, element.value); else if (element.type === 'checkbox' || element.type === 'radio') capture(element.checked ? 'check' : 'uncheck', element); }, true);
document.addEventListener('keydown', (event) => { if (recording && event.key === 'Enter' && !(event.target instanceof HTMLInputElement && isSensitive(event.target))) capture('press', event.target as Element, 'Enter'); }, true);
chrome.runtime.onMessage.addListener((message: RuntimeMessage) => {
  if (message.type === 'START_SESSION') {
    recording = true;
    const href = location.href;
    if (document.hasFocus()
        && href
        && !href.startsWith('chrome://')
        && !href.startsWith('about:')
        && !href.startsWith('chrome-extension://')) {
      const nav = action('navigate', undefined, href);
      if (nav) emit({ type: 'ACTION', action: nav });
    }
  }
  if (message.type === 'STOP_SESSION') recording = false;
});
chrome.runtime.onMessage.addListener((message: RuntimeMessage) => { if (message.type === 'ACTION_RECORDED') window.postMessage({ source: 'actionpilot-extension', action: message.action }, '*'); });
chrome.runtime.sendMessage({ type: 'GET_STATE' } satisfies RuntimeMessage, (state) => { recording = state?.status === 'recording'; });
window.addEventListener('message', (event) => { if (event.source !== window || event.data?.source !== 'actionpilot') return; if (event.data.type === 'START_TEACHING') emit({ type: 'START_SESSION', sessionId: event.data.sessionId }); });
