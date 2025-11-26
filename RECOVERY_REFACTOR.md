# Recovery Daemon Refactoring

## Overview

The recovery daemon has been completely refactored from `litter_robot_recovery.py` to `recovery_daemon.py` with a cleaner, more robust architecture.

---

## Key Improvements

### 1. **Fully Async Architecture**

**Old:**
```python
def safe_sync_run(func, *args, **kwargs):
    result = asyncio.get_event_loop().run_until_complete(func(*args, **kwargs))
```
- Used deprecated `get_event_loop()`
- Mixed sync `schedule` library with async code
- Created/destroyed event loops constantly

**New:**
```python
async def run(self):
    async with self.robot_client:
        while self._running:
            await self.check_and_recover()
            await asyncio.sleep(self.config.check_interval_seconds)
```
- Pure async with `asyncio.run()`
- Proper async context managers
- Clean async/await throughout

---

### 2. **Persistent Connection Management**

**Old:**
- Created new API connection **every minute**
- Reconnected for every status check
- No connection pooling

**New:**
```python
class RobotClient:
    async def ensure_connected(self):
        if not self._connected:
            await self.connect()
```
- Maintains persistent connection
- Automatic reconnection on failure
- Connection reuse via context manager

---

### 3. **Smart Error Classification**

**Old:**
```python
ERROR_STATES = {
    LitterBoxStatus.DRAWER_FULL,    # Can't fix with power cycle!
    LitterBoxStatus.BONNET_REMOVED, # Needs human intervention
    LitterBoxStatus.PAUSED,         # Might be intentional
    ...
}
```
All errors treated the same way.

**New:**
```python
class RecoveryAction(Enum):
    NONE         # Normal operation
    WAIT         # Transient, will resolve
    POWER_CYCLE  # Auto-recoverable
    NOTIFY_USER  # Needs human help

STATUS_ACTIONS = {
    LitterBoxStatus.DRAWER_FULL: RecoveryAction.NOTIFY_USER,
    LitterBoxStatus.OVER_TORQUE_FAULT: RecoveryAction.POWER_CYCLE,
    LitterBoxStatus.CLEAN_CYCLE: RecoveryAction.WAIT,
    ...
}
```
- Categorized by **what action to take**
- Power cycling only for fixable errors
- Notifications for user intervention
- Patience for transient states

---

### 4. **Dependency Injection & Testability**

**Old:**
- Global module-level config
- Hard-coded dependencies
- Impossible to unit test

**New:**
```python
def create_daemon(config: Config) -> RecoveryDaemon:
    robot_client = RobotClient(...)
    plug = SmartPlugController(...)
    notifier = WebhookNotifier(...) if config.webhook_url else LogNotifier()
    state_store = StateStore(...)

    return RecoveryDaemon(
        config=config,
        robot_client=robot_client,
        plug=plug,
        notifier=notifier,
        state_store=state_store,
    )
```
- All dependencies injected
- Easy to mock for testing
- Interface-based design

---

### 5. **State Persistence**

**Old:**
- State lost on restart
- No crash recovery
- Could trigger duplicate recoveries

**New:**
```python
class StateStore:
    def save(self, state: MonitorState):
        self.path.write_text(state.to_json())

    def load(self) -> MonitorState:
        return MonitorState.from_json(self.path.read_text())
```
- State saved to `recovery_state.json`
- Survives crashes/restarts
- Tracks recovery history

---

### 6. **Notification System**

**Old:**
- Only logs to file/console
- No alerts when manual intervention needed
- No way to know daemon status

**New:**
```python
class Notifier(ABC):
    async def send(self, title: str, message: str, severity: str):
        pass

class WebhookNotifier(Notifier):
    # Send to Discord, Slack, ntfy, etc.

class LogNotifier(Notifier):
    # Fallback when no webhook configured
```
- Pluggable notification backends
- Alerts when user attention required
- Configurable via `WEBHOOK_URL` in `.env`

---

### 7. **Strategy Pattern for Recovery**

**Old:**
- Hard-coded 7-step sequence
- Same recovery for all errors
- Inflexible

**New:**
```python
class RecoveryStrategy(ABC):
    async def execute(self, robot: Robot, attempt: int) -> bool:
        pass

class PowerCycleRecovery(RecoveryStrategy):
    async def execute(self, robot: Robot, attempt: int) -> bool:
        # 1. Power cycle
        # 2. Wait for boot
        # 3. Check status
        # 4. Try clean cycle if needed
```
- Pluggable strategies
- Easy to add new recovery methods
- Adaptable based on error type

---

### 8. **Type Safety**

**Old:**
- No type hints
- Runtime errors
- Hard to understand data flow

**New:**
```python
@dataclass
class Config:
    whisker_username: str
    whisker_password: str
    check_interval_seconds: int = 60
    error_timeout_minutes: int = 30
```
- Full type annotations
- Dataclasses for configuration
- IDE autocomplete and type checking

---

## Usage Comparison

### Old Daemon

```bash
python litter_robot_recovery.py
```

**Configuration:** Environment variables loaded at module level
**Logging:** `litter_robot_recovery.log`
**State:** Lost on restart
**Notifications:** None

---

### New Daemon

```bash
python recovery_daemon.py
```

**Configuration:** `Config.from_env()` with validation
**Logging:** `recovery_daemon.log` with structured format
**State:** Persisted to `recovery_state.json`
**Notifications:** Optional webhook via `WEBHOOK_URL`

---

## Testing

### Old Daemon
- No tests possible
- Must run against real API
- Can't mock dependencies

### New Daemon

```bash
python test_daemon.py  # Single check, then exit
```

- Unit testable with mocks
- Integration test script included
- Dependency injection enables testing

---

## Configuration

Add to `.env`:

```bash
# Optional: Check interval (default: 60s)
CHECK_INTERVAL_SECONDS=60

# Optional: How long to wait before attempting recovery (default: 30 min)
ERROR_TIMEOUT_MINUTES=30

# Optional: Webhook for notifications (Discord, Slack, ntfy, etc.)
WEBHOOK_URL=https://ntfy.sh/your-topic
```

---

## Migration Guide

1. **Stop old daemon** if running
2. **Run new daemon:**
   ```bash
   python recovery_daemon.py
   ```
3. **State file** will be created at `recovery_state.json`
4. **(Optional)** Configure webhook notifications in `.env`
5. **Old daemon** can be kept as backup or removed

---

## Architecture Diagram

```
┌─────────────────────────────────────────┐
│         RecoveryDaemon                  │
│   (Orchestrates monitoring loop)        │
└────────────┬────────────────────────────┘
             │
   ┌─────────┼──────────┬─────────────┐
   ▼         ▼          ▼             ▼
┌──────┐ ┌──────┐ ┌─────────┐ ┌──────────┐
│Robot │ │Smart │ │Notifier │ │StateStore│
│Client│ │Plug  │ │         │ │          │
└──────┘ └──────┘ └─────────┘ └──────────┘
   │
   ▼
┌─────────────────────────────────────────┐
│       StateClassifier                   │
│  (Categorizes errors by action)         │
└─────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────┐
│     RecoveryStrategy                    │
│  - PowerCycleRecovery                   │
│  - (Future: SoftResetRecovery, etc.)    │
└─────────────────────────────────────────┘
```

---

## Benefits Summary

| Aspect | Old | New |
|--------|-----|-----|
| **Architecture** | Sync/async mess | Fully async |
| **Connections** | New every check | Persistent, managed |
| **Error Handling** | All errors same | Smart classification |
| **Recovery** | Rigid 7-step | Pluggable strategies |
| **State** | Lost on crash | Persisted to disk |
| **Notifications** | None | Webhook support |
| **Testing** | Impossible | Fully testable |
| **Type Safety** | None | Full annotations |
| **Lines of Code** | 502 | 650 (but cleaner) |

---

## Future Enhancements

Possible improvements now that the architecture supports them:

1. **Multiple recovery strategies**
   - Soft reset before power cycle
   - Wait-and-retry for transient errors
   - Progressive escalation

2. **Advanced notifications**
   - Email support
   - SMS via Twilio
   - Push notifications

3. **Metrics and monitoring**
   - Prometheus metrics
   - Health check endpoint
   - Recovery success rate tracking

4. **Multi-robot support**
   - Monitor multiple robots
   - Per-robot configuration
   - Aggregate status reporting

5. **Smart scheduling**
   - Adaptive check intervals
   - Skip checks during scheduled clean times
   - Rate limiting for API calls
