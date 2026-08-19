# Generated contracts

Files under `contracts/v1/` are generated from the separated registries in `src/ai_edit_machine/contracts.py`. Do not edit them directly.

```powershell
python scripts/export_contract_schemas.py
python scripts/export_contract_schemas.py --check
```

Layout:

- `provider/{xai,openai,gemini}/`: required-field conservative baselines for model-authored drafts;
- `canonical/`: trusted persisted record schemas;
- `execution/`: backend-only cost and compiled-plan schemas, never sent to a model.

The provider schemas are offline lowerer seeds, not proof of live API compatibility. Milestone 1 must record provider-specific conformance fixtures. Canonical strict Pydantic and independent domain validation remain mandatory.
