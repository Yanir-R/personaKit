# Security policy

PersonaKit handles personal conversation data, so privacy and security reports are taken seriously.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting:
**Security tab -> Report a vulnerability**.

Include what you found, how to reproduce it, and what data could be exposed. You can expect an
acknowledgement within a few days. This is a pre-release project maintained by one person, so
fixes are best-effort, but anything that could expose a user's memories is prioritised.

## Scope

In scope: leaking owner data (to a model, an assistant, logs or the network beyond what
`docs/PRIVACY.md` states), bypassing a memory's scope or state, unsafe handling of session files.

## Supported versions

Only the latest release and `main`.
