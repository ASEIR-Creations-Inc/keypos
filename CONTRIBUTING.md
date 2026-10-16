# Contributing to KEYPOS

Thanks for your interest! KEYPOS is a **development preview**. It works in a real shop, but
large parts are still unfinished, and help is very welcome.

## Where help is most needed

1. **SAF-T and tax compliance.** SAF-T (AO) export, signed and chained fiscal documents,
   several IVA rates with exemption codes, the right document types, and the path to
   certification by Angola's AGT (or the equivalent body where you live). Even if you don't
   write code, an issue that explains a rule and links the official source is a big help.
2. Receipt printing (Bluetooth and USB thermal printers).
3. Translations beyond English and Portuguese.
4. Testing on more phones, especially old Android versions.

## How to contribute

1. **Open an issue first** for anything bigger than a small fix, so we can agree on the
   approach before you spend time on it.
2. Fork the repo and create a branch from `main`.
3. Keep changes small and focused, one topic per pull request.
4. Add or update tests:
   - backend: `cd backend && pytest -q`
   - frontend and API: `cd tests && ./testenv.sh up && ./sweep.sh`
5. After changing frontend JavaScript, run `python3 tools/stamp.py`.
6. Open a pull request that explains what changed and why.

## Ground rules of the project

These rules come from how the shop actually works. Please keep them:

- **Nothing that moves stock, cash, card or a customer account happens without an audit
  record** naming the person, the shift and, where it matters, the reason.
- The audit trail is append-only. Never add a way to edit or delete it.
- Refunds always cover the whole receipt and need a reason.
- The frontend is plain ES5 with no build step, so it still runs on old Android WebViews.
- Money is stored as decimals, never floats.

## License of contributions

KEYPOS is licensed under the [AGPL-3.0](LICENSE). By opening a pull request you agree that
your contribution is released under the same license.

## Reporting security problems

Please don't open a public issue for a security problem. Use GitHub's
**"Report a vulnerability"** button on the Security tab of this repository instead.
