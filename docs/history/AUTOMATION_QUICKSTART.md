# Blueprint Automation quick start

Audit first; compact JSON is designed for agents and humans:

```bash
bpfw batch audit --json
```

Create a batch plan (no authority write yet):

```bash
bpfw batch default \
  --scope artifact \
  --where type=code \
  --field required \
  --value true \
  --json
```

Apply the returned plan only after review:

```bash
bpfw batch apply PLAN_ID
```

Other useful commands:

```bash
bpfw batch generate-uids --json
bpfw batch discover-artifacts --unbound --json
bpfw normalize --json
bpfw compact --json
bpfw verify
```

Example compact metadata:

```yaml
defaults:
  artifacts:
    required: true
    code:
      language: go

profiles:
  go_runtime:
    type: code
    language: go
    role: implementation
    required: true

# In a block:
artifacts:
  - id: perception_runtime
    profile: go_runtime
    path: internal/perception/runtime.go
    kind: method
    symbol: Runtime.Run
```

BPFW materializes inherited fields in memory. It does not need to repeat them in every artifact.
