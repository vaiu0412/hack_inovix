"""WebSockets: /ws/partner and /ws/admin stream the change feed (store.changes_since) as it happens.

One shared poller reads new rows of the `changes` table every second and hands each to the sockets allowed to
see it – so it works across processes (the Streamlit app and the API write to the same database), on SQLite and
PostgreSQL alike. The Streamlit screens keep polling the data version as before (fallback, nothing to set up).

Protocol (JSON):
  connect   ws://host/ws/partner?token=<access token>[&since=<id>]   (or /ws/admin)
  server -> {"type": "hello", "role": ..., "last_id": n}            then, for every change it may see:
            {"type": "change", "id": n, "kind": "offer" | "event" | "message", "time": ..., "branch_id": ...,
             "dp_id": ..., "data": {...}}
  client -> "ping"   server -> {"type": "pong"}
Closes with 4401 (no or invalid token, or the session ended) or 4403 (wrong role).
Who sees what: a partner only rows addressed to them (their offers and messages); a branch admin every row of
their branch; a super admin every row.
"""
import asyncio
import contextlib

from fastapi import WebSocket, WebSocketDisconnect

from modules import store

POLL_SEC = 1.0
RECHECK_SEC = 60  # how often an open socket re-checks its session (sign-out / deactivation cut it off)


class Hub:
    """The open sockets and one poller that feeds them."""

    def __init__(self):
        self.queues = {}
        self.task = None
        self.last_id = 0
        self.polls = 0

    async def join(self, accepts):
        """Register a socket's filter; returns its queue of rows."""
        if self.task is None or self.task.done():
            self.last_id = await asyncio.to_thread(store.last_change_id)
            self.task = asyncio.create_task(self._poll())
        queue = asyncio.Queue(maxsize=1000)
        self.queues[queue] = accepts
        return queue

    def leave(self, queue):
        """Forget a closed socket."""
        self.queues.pop(queue, None)

    async def _poll(self):
        while self.queues:
            await asyncio.sleep(POLL_SEC)
            try:
                rows = await asyncio.to_thread(store.changes_since, self.last_id, None, None, 500)
                self.polls += 1
                if self.polls % 600 == 0:
                    await asyncio.to_thread(store.prune_changes)
            except Exception:  # database busy or restarting: try again next second
                continue
            for row in rows:
                self.last_id = max(self.last_id, row["id"])
                for queue, accepts in list(self.queues.items()):
                    if accepts(row) and not queue.full():
                        queue.put_nowait(row)


HUB = Hub()


def scope(user):
    """What a signed-in user may see of the feed."""
    if user["role"] == "partner":
        return lambda row: row["dp_id"] == user["dp_id"] and row["branch_id"] == user["branch_id"]
    if user["role"] == "branch_admin":
        return lambda row: row["branch_id"] == user["branch_id"]
    return lambda row: True


def _message(row):
    return {"type": "change", **{k: row[k] for k in ("id", "kind", "time", "branch_id", "dp_id", "data")}}


async def stream(websocket: WebSocket, user_for_token, token, since, roles):
    """Serve one socket until the client leaves or its session ends."""
    await websocket.accept()
    user = await asyncio.to_thread(user_for_token, token)
    if user is None:
        await websocket.close(code=4401, reason="Sign in first")
        return
    if user["role"] not in roles:
        await websocket.close(code=4403, reason="Not for your role")
        return
    accepts = scope(user)
    queue = await HUB.join(accepts)
    sent = HUB.last_id
    receiver = asyncio.create_task(_receive(websocket))
    try:
        await websocket.send_json({"type": "hello", "role": user["role"], "last_id": sent})
        if since is not None:  # catch up on what was missed while offline (bounded)
            mine = [r for r in await asyncio.to_thread(store.changes_since, since, None, None, 500) if accepts(r)]
            for row in mine:
                await websocket.send_json(_message(row))
                sent = max(sent, row["id"])
        while True:
            getter = asyncio.create_task(queue.get())
            done, _ = await asyncio.wait({getter, receiver}, timeout=RECHECK_SEC,
                                         return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                getter.cancel()
                break
            if getter in done:
                row = getter.result()
                if row["id"] > sent:
                    await websocket.send_json(_message(row))
                    sent = row["id"]
            else:
                getter.cancel()
                if await asyncio.to_thread(user_for_token, token) is None:
                    await websocket.close(code=4401, reason="Session ended")
                    break
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        HUB.leave(queue)
        receiver.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await receiver


async def _receive(websocket):
    """Answer pings; returns when the client goes away."""
    try:
        while True:
            text = await websocket.receive_text()
            if text.strip().lower() == "ping":
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, RuntimeError):
        return
