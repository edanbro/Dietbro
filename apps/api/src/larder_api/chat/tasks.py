"""Chat turns run detached from the HTTP connection.

`ChatTurns` lives on app.state (created in the lifespan): `start(prepared, scope_factory)`
starts `service.run_turn` as a task in a long-lived anyio task group and returns an
`anyio.abc.ObjectReceiveStream` of ChatEvents (buffer large enough that a slow phone never
back-pressures the model stream; text deltas may be coalesced). The SSE endpoint only relays
that stream; when the client disconnects, the relay stops and the turn carries on, persists its
reply and releases the turn lock. Sends to a closed stream are ignored. Each turn runs under
`anyio.fail_after(chat_turn_deadline_s)`; lifespan shutdown waits for running turns up to that
deadline, then cancels them (their `finally` still releases the lock, shielded).
"""
