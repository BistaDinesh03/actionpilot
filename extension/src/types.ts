export type ActionType = 'click' | 'type' | 'navigate' | 'select' | 'check' | 'uncheck' | 'press' | 'submit';
export type Target = { tag?: string; role?: string; name?: string; text?: string; label?: string; placeholder?: string; test_id?: string; css?: string; xpath?: string };
export type BrowserAction = { type: ActionType; timestamp: string; url: string; title: string; target?: Target; value?: string };
export type RecorderState = { status: 'idle' | 'recording' | 'disconnected'; sessionId?: string; name?: string };
export type RuntimeMessage = { type: 'START_SESSION'; sessionId: string; name?: string } | { type: 'START_FROM_POPUP'; name: string; description: string } | { type: 'STOP_SESSION' } | { type: 'GET_STATE' } | { type: 'ACTION'; action: BrowserAction } | { type: 'ACTION_RECORDED'; action: BrowserAction };
