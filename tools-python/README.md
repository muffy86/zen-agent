# zen-agent — python head

The Python implementation of the shared protocol: same registry, same gate, same decisions as the
TypeScript and Kotlin heads. It is the head used for scripting, data work and MCP servers.

```bash
python -m zen_agent.cli selftest
python -m zen_agent.cli conformance          # all golden vectors
python -m zen_agent.cli route --capability code --prefer local --json
python -m zen_agent.cli live --prompt 'reply with exactly: ZEN_OK'
python -m zen_agent.cli doctor               # live-probe every provider
pytest                                        # the same vectors as tests
```

Importable API:

```python
from zen_agent import load_registry, route, run_live_loop, load_rules, MemoryStore

decision = route(load_registry(), {"capability": "code", "prefer": "local"})
outcome = run_live_loop(decision, "compute 21*2 with the calc tool", ctx)
```
