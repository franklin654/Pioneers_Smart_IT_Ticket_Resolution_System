# BUG-001 — BaseRepository.delete() silently fails (missing await)

**Severity:** High  
**Component:** `src/db/repositories/base_repo.py`  
**Discovered by:** Integration test `tests/integration/test_repositories.py::TestTicketRepository::test_delete_existing_returns_true`  
**Date:** 2026-06-08

---

## Summary

`BaseRepository.delete()` calls `self.session.delete(obj)` without `await`.  
In SQLAlchemy 2.x `AsyncSession`, `delete()` is a coroutine — calling it without `await`
creates a coroutine object that is immediately garbage-collected without executing.
The subsequent `session.flush()` finds no pending delete and does nothing.
The record remains in the database.

---

## Affected Code

**File:** `src/db/repositories/base_repo.py`, line 82

```python
# BROKEN — coroutine is created but never awaited
async def delete(self, record_id: uuid.UUID) -> bool:
    obj = await self.get_by_id(record_id)
    if obj is None:
        return False
    self.session.delete(obj)   # ← missing await
    await self.session.flush()
    return True
```

**Python warning emitted at runtime:**
```
RuntimeWarning: coroutine 'AsyncSession.delete' was never awaited
  self.session.delete(obj)
```

---

## Impact

- Any call to `BaseRepository.delete()` (or a subclass that delegates to it) returns
  `True` but leaves the database row intact.
- Affected endpoints / scripts: any route or script that deletes a ticket via the API
  (e.g. `DELETE /api/v1/tickets/{id}`).
- Secondary risk: if a caller checks the return value and trusts `True` = "deleted",
  downstream logic (e.g. freeing related resources, audit logging) may act on stale state.

---

## Reproduction

```python
# Integration test (marked xfail until fixed):
# tests/integration/test_repositories.py::TestTicketRepository::test_delete_existing_returns_true
repo = TicketRepository(session)
created = await repo.create(ticket)
deleted = await repo.delete(created.id)
assert deleted is True                          # passes (returns True)
assert await repo.get_by_id(created.id) is None  # FAILS — record still exists
```

---

## Fix

Add `await` to line 82 of `src/db/repositories/base_repo.py`:

```python
# FIXED
await self.session.delete(obj)
await self.session.flush()
return True
```

---

## Verification

After applying the fix, remove the `@pytest.mark.xfail` decorator from
`tests/integration/test_repositories.py::TestTicketRepository::test_delete_existing_returns_true`
and confirm the test passes.
