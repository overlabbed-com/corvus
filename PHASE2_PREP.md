# Phase 2: Reliability & Performance - Preparation

**Status**: Preparing while Phase 1 CI runs  
**Goal**: Begin implementation immediately after Phase 1 passes tollgate

## Phase 2 Stories (8 total)

### Priority Order (based on risk and dependencies)

1. **Story 2.1**: Fix Silent Constraint Failures (Issue #4)
   - Risk: High - Partial schema failures undetected
   - Effort: 4h
   - Dependency: None
   
2. **Story 2.2**: Fix Exception Suppression in Migrations (Issue #5)
   - Risk: Medium - Real failures silently ignored
   - Effort: 2h
   - Dependency: None
   
3. **Story 2.3**: Fix SSE Memory Leak (Issue #6)
   - Risk: High - Resource exhaustion under load
   - Effort: 6h
   - Dependency: None
   
4. **Story 2.4**: Fix SIEM Race Condition (Issue #7)
   - Risk: Medium - Already partially fixed in Phase 1
   - Effort: 2h
   - Dependency: Phase 1.2 complete
   
5. **Story 2.5**: Add Composite Indexes (Issue #9)
   - Risk: Low - Performance optimization
   - Effort: 2h
   - Dependency: None
   
6. **Story 2.6**: Fix LIKE Query Inefficiency (Issue #10)
   - Risk: Low - Slow queries under load
   - Effort: 4h
   - Dependency: None
   
7. **Story 2.7**: Make Baselines Configurable (Issue #11)
   - Risk: Medium - Static baselines become stale
   - Effort: 4h
   - Dependency: None
   
8. **Story 2.8**: Fix Queue Full Silent Drop (Issue #12)
   - Risk: Medium - Events lost during spikes
   - Effort: 4h
   - Dependency: None

## Adversarial Tie-Breaking

### Question: Which story has highest impact vs effort?

**Architect Analysis**:
- Highest impact: Story 2.3 (SSE memory leak) - prevents resource exhaustion
- Lowest effort: Story 2.2, 2.5 (2h each)
- Best ratio: Story 2.2 (exception suppression) - 2h, medium risk

**Advocate Analysis (Adversarial)**:
- Story 2.1 could break startup if constraints fail
- Story 2.3 has complex cleanup logic - risk of introducing new leaks
- Story 2.4 is redundant - already fixed in Phase 1.2
- **Recommendation**: Start with 2.2 (safe), then 2.5 (quick win), then 2.1 (high risk)

**Reviewer Analysis (Code Quality)**:
- Story 2.2: Clean, well-scoped change
- Story 2.5: Simple schema change, zero runtime risk
- Story 2.1: Requires transaction handling - more complex
- **Recommendation**: 2.2 → 2.5 → 2.1

### Consensus: Start with Stories 2.2, 2.5, 2.1

**Order**:
1. **Story 2.2** (2h) - Fix exception suppression in migrations
2. **Story 2.5** (2h) - Add composite indexes (quick win)
3. **Story 2.1** (4h) - Fix silent constraint failures (high risk)
4. **Story 2.8** (4h) - Fix queue full silent drop
5. **Story 2.7** (4h) - Make baselines configurable
6. **Story 2.3** (6h) - Fix SSE memory leak (complex)
7. **Story 2.6** (4h) - Fix LIKE query inefficiency
8. **Story 2.4** (2h) - Verify SIEM race condition fixed

## Implementation Plan

### Day 1: Quick Wins (Stories 2.2, 2.5)

**Story 2.2: Fix Exception Suppression**
```python
# database.py
import sqlite3

for alter_sql in alter_statements:
    try:
        await db.execute(alter_sql)
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e).lower():
            logger.error(f"Migration error: {e}")
            raise
```

**Story 2.5: Add Composite Indexes**
```sql
CREATE INDEX IF NOT EXISTS idx_events_context 
ON ops_events(timestamp DESC, severity, type);

CREATE INDEX IF NOT EXISTS idx_problems_gap 
ON ops_problems(pattern, status);

CREATE INDEX IF NOT EXISTS idx_triage_analytics 
ON ops_triage_log(timestamp, service_type, outcome);
```

### Day 2: High Risk (Story 2.1)

**Story 2.1: Fix Silent Constraint Failures**
```python
# graph.py - wrap in transaction with error checking
async def init_graph():
    async with driver.session() as session:
        try:
            async with session.begin_transaction():
                for constraint in constraints:
                    await session.run(constraint)
                # All succeeded
        except Exception as e:
            logger.error(f"Constraint creation failed: {e}")
            raise
```

### Day 3: Event Handling (Stories 2.8, 2.7)

**Story 2.8: Fix Queue Full Silent Drop**
```python
# event_bus.py
async def publish(event: dict):
    try:
        await asyncio.wait_for(
            self._event_queue.put(event),
            timeout=5.0
        )
    except asyncio.TimeoutError:
        logger.error(f"Queue full, dropping event: {event.get('id')}")
        # Expose metric
```

**Story 2.7: Make Baselines Configurable**
```python
# gap_detection.py
# Move RESOLUTION_BASELINES to CMDB or config
async def get_baseline(service_type: str) -> int:
    cursor = await db.execute(
        "SELECT baseline_behavior FROM ops_cmdb WHERE name = ?",
        (service_type,)
    )
    # Auto-tune from historical data
```

### Day 4: Complex Fixes (Story 2.3)

**Story 2.3: Fix SSE Memory Leak**
```python
# event_bus.py
async def subscribe():
    subscriber_id = str(uuid.uuid4())
    queue = asyncio.Queue(maxsize=1000)
    self._subscribers[subscriber_id] = queue
    
    # Add heartbeat
    while True:
        try:
            await asyncio.wait_for(
                queue.get(),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            # Send heartbeat
            await queue.put({"type": "heartbeat"})
    
    # Cleanup on disconnect
    del self._subscribers[subscriber_id]
```

### Day 5: Optimization (Stories 2.6, 2.4)

**Story 2.6: Fix LIKE Query Inefficiency**
```python
# events.py - replace LIKE with JSON extraction
# Instead of: WHERE targets LIKE ?
# Use: WHERE json_extract(targets, '$[0]') = ?
```

**Story 2.4: Verify SIEM Race Condition**
- Already fixed in Phase 1.2 with asyncio.Lock
- Add test to verify concurrent access is safe

## Test Strategy

For each story:
1. Write failing test first
2. Implement minimum code to pass
3. Run full test suite to check regressions
4. Commit with descriptive message

## Success Criteria for Phase 2

- [ ] All 8 stories implemented
- [ ] 30+ new tests added
- [ ] No test regressions
- [ ] Performance benchmarks show improvement
- [ ] Memory usage stable under load
- [ ] Query latency reduced

## Tollgate to Phase 3

- [ ] All Phase 2 tests passing
- [ ] Performance metrics collected
- [ ] Memory leak verified fixed
- [ ] Code review complete
- [ ] PR merged to main

---

**Ready to execute** when Phase 1 passes tollgate.
