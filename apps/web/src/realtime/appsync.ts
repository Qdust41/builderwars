import type { RealtimeClient, RealtimeEvent, Unsubscribe } from "./types";

/**
 * AWS AppSync Events adapter — NOT IMPLEMENTED.
 *
 * TODO:
 *  - Connect to the Events API WebSocket endpoint with the user's Cognito ID token.
 *  - Subscribe to `/<namespace>/projects/{projectId}/sessions/{sessionId}` only after the API's
 *    GET /sessions/{id}/channel confirmed membership; the server-side onSubscribe handler must
 *    re-check membership.
 *  - Validate incoming events against the realtime contract; drop unknown types.
 *  - On reconnect, refetch state from the API (events may have been missed).
 * Keep all AppSync-specific code in this module.
 */
export class AppSyncEventsClient implements RealtimeClient {
  constructor(private readonly endpoint: string) {}

  async subscribe(_channel: string, _onEvent: (e: RealtimeEvent) => void): Promise<Unsubscribe> {
    throw new Error(`AppSync Events realtime client not implemented (endpoint ${this.endpoint})`);
  }
}
