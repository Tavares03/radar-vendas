# radar-vendas (backend)

Pacote Python `radar`: biblioteca de análise, API FastAPI e worker do Radar de Vendas.

Veja o [README principal](../README.md) para instalar e usar, e
[docs/ARQUITETURA.md](../docs/ARQUITETURA.md) para entender como os módulos se encaixam.

```bash
uv sync                      # na raiz do repositório
uv run radar --help          # CLI
uv run uvicorn radar.api.app:app --reload
uv run pytest backend/tests
```
