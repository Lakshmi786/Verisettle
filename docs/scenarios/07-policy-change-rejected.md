# 07 — Policy change rejected

**What this proves:** the same validator genuinely blocks a bad policy change — both an obvious mistake and a subtle one.

Both cases below work on real **copies** of the policy files, inside a
`.scratch/` folder (gitignored, safe to delete any time) — **the real
`policies/*.cedar` files are never touched.** There's nothing to revert
afterward; just delete `.scratch/` when you're done, or leave it, it's
never read by anything else.

## Steps — an obviously bad rule

```sh
mkdir -p .scratch/bad-policy-a
cp policies/*.cedar policies/*.cedarschema.json .scratch/bad-policy-a/
cat >> .scratch/bad-policy-a/99-overly-permissive.cedar <<'EOF'
permit (principal, action, resource);
EOF
```

**macOS/Linux:**
```sh
docker run --rm -v "$(pwd)/.scratch/bad-policy-a:/policies:ro" -v "$(pwd)/infra/scripts:/scripts:ro" \
  verisettle-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```

**Windows (Git Bash):** 
```sh
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)/.scratch/bad-policy-a:/policies:ro" -v "$(pwd)/infra/scripts:/scripts:ro" \
  verisettle-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```

## Steps — a subtle bad change

```sh
mkdir -p .scratch/bad-policy-b
cp policies/*.cedar policies/*.cedarschema.json .scratch/bad-policy-b/
sed -i 's/5000/500000/g' .scratch/bad-policy-b/01-agent-approval-threshold.cedar
```

**macOS/Linux:**
```sh
docker run --rm -v "$(pwd)/.scratch/bad-policy-b:/policies:ro" -v "$(pwd)/infra/scripts:/scripts:ro" \
  verisettle-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```

**Windows (Git Bash):**
```sh
MSYS_NO_PATHCONV=1 docker run --rm -v "$(pwd)/.scratch/bad-policy-b:/policies:ro" -v "$(pwd)/infra/scripts:/scripts:ro" \
  verisettle-policy-service:latest python3 /scripts/validate-cedar-policies.py /policies
```


## Cleanup (optional)

```sh
rm -rf .scratch/bad-policy-a .scratch/bad-policy-b
```
Not required — `.scratch/` is gitignored either way — but tidy if you want it gone.
