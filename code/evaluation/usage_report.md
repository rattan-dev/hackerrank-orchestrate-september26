# Token Usage and Cost Report

## Final full-dataset run

- Requests processed: 250
- Token-based model provider/name: none (deterministic final run)
- LLM calls: 0
- Input tokens: 0 total; 0 average per request
- Output tokens: 0 total; 0 average per request
- Estimated token cost: USD 0 total; USD 0 per request
- OCR preprocessing runtime: Tesseract 5.3.4 with Leptonica 1.82.0. It was used to inspect 16 supplied PNG files and is not token-metered. Reviewed results are stored in `config/image_facts.csv`, so the final full-dataset run made 0 OCR calls.

The optional schema-constrained LLM extraction path was disabled because no endpoint was configured for the final run. It therefore contributed no calls, tokens, or cost to the submitted `output.csv`. Mocked adversarial tests exercise its schema and fallback behavior, but this report does not represent those mocks as live model usage.
